"""The Strands adapter: the only place in the project that talks to an LLM.

Everything the SDK knows is confined here. :mod:`extractors.process` depends on
the :class:`~extractors.process.ModelCall` protocol instead, and the
conversation's agents on :mod:`extractors.conversation`, which is what lets the
retry loop and a whole session be tested without a network.

Two adapters, one translation. :class:`StrandsModelCall` is the one-shot
extraction's; :class:`StrandsConversation` is the general form any agent uses.
Both turn the SDK's exceptions into the same two of ours through
:func:`_translated`, so the retry taxonomy cannot come to differ between them.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from anthropic import APIStatusError
from pydantic import BaseModel
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands.types.exceptions import MaxTokensReachedException, StructuredOutputException

from extractors.conversation import T
from extractors.errors import ModelUnavailableError, SchemaCallError
from extractors.prompt import build_system_prompt
from ir.models import ProcessGraph
from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton
from utils.logs import record_call
from utils.settings import Settings


class StrandsModelCall:
    """A :class:`~extractors.process.ModelCall` backed by a Strands agent.

    The agent is held across calls on purpose: a repair turn continues the same
    conversation, so the model sees its own previous graph next to the critique
    rather than re-extracting from scratch.
    """

    def __init__(self, agent: "_TracedAgent") -> None:
        self._agent = agent

    def __call__(self, prompt: str) -> ProcessGraph:
        """Send one turn and return the parsed graph.

        Raises:
            SchemaCallError: If the model failed to produce a graph in the schema.
                Transport and API failures are deliberately left to propagate --
                a rate limit is not something a repair prompt can fix.
        """
        return self._agent.ask(prompt, ProcessGraph)


def build_model_call(settings: Settings, config: ProcessConfig, skeleton: Skeleton) -> StrandsModelCall:
    """Build the callable the extraction loop drives.

    Args:
        settings: Global settings supplying credentials and model defaults.
        config: Per-process settings, which may override the model.
        skeleton: The subprocesses this process is expected to contain.

    Returns:
        A model call wrapping an agent primed with the extraction system prompt.
    """
    model_id = config.model_id or settings.model_id
    system_prompt = build_system_prompt(config, skeleton)
    model = AnthropicModel(
        client_args=_client_args(settings),
        model_id=model_id,
        max_tokens=settings.max_tokens,
        # No temperature/top_p/top_k: the current Claude models reject them.
    )
    return StrandsModelCall(
        _TracedAgent(
            Agent(model=model, system_prompt=system_prompt, callback_handler=None),
            role=ONE_SHOT,
            model_id=model_id,
            system_prompt=system_prompt,
        )
    )


WORKSPACE_HEADER = "anthropic-workspace-id"

ONE_SHOT = "one_shot"
"""The role the one-shot extraction is traced under, beside the conversation's three."""


class _TracedAgent:
    """One Strands agent, with every call through it timed, translated and recorded.

    Both adapters hold one of these and nothing else, so there is exactly one
    place a model is called from -- which is what lets the trace promise it has
    every call. The agent is built with no callback handler: Strands' default
    one prints the model's output to stdout as it streams, and what this project
    wants on the console is its own account of the call, written once it is over.
    """

    def __init__(
        self,
        agent: Agent,
        *,
        role: str,
        model_id: str,
        system_prompt: str,
        cached_context: str | None = None,
    ) -> None:
        self._agent = agent
        self._role = role
        self._model_id = model_id
        self._system_prompt = system_prompt
        self._cached_context = cached_context
        self._seen: dict[str, int] = {}

    def ask(self, prompt: str, output: type[T]) -> T:
        """Send one turn and return the parsed answer, recording the call either way.

        Raises:
            SchemaCallError: If the model failed to answer in the schema.
            ModelUnavailableError: If the API rejected the request.
        """
        started = time.perf_counter()
        try:
            with _translated():
                result = self._agent(prompt, structured_output_model=output)
            answer: BaseModel | None = result.structured_output
            if not isinstance(answer, output):
                raise SchemaCallError(f"expected a {output.__name__}, got {type(answer).__name__}")
        except Exception as error:
            # Recorded and re-raised: a failed call is the one most worth being able to read back.
            self._record(prompt, output, started, error=f"{type(error).__name__}: {error}")
            raise
        self._record(prompt, output, started, response=answer.model_dump(mode="json"))
        return answer

    def _record(
        self,
        prompt: str,
        output: type[BaseModel],
        started: float,
        *,
        response: object | None = None,
        error: str | None = None,
    ) -> None:
        record_call(
            role=self._role,
            model_id=self._model_id,
            system_prompt=self._system_prompt,
            cached_context=self._cached_context,
            prompt=prompt,
            output_type=output.__name__,
            seconds=time.perf_counter() - started,
            response=response,
            error=error,
            usage=self._usage_since_last_call(),
        )

    def _usage_since_last_call(self) -> dict[str, int]:
        """This call's tokens. The agent reports a running total, so the last total is subtracted."""
        total = {
            key: int(value)
            for key, value in dict(self._agent.event_loop_metrics.accumulated_usage).items()
            if isinstance(value, int)
        }
        spent = {key: value - self._seen.get(key, 0) for key, value in total.items()}
        self._seen = total
        return spent


def _client_args(settings: Settings) -> dict[str, Any]:
    """What the Anthropic client is built with: the key, and the workspace if one is named.

    One function for both adapters, so the one-shot path and the conversation
    cannot come to authenticate differently. The workspace travels as a default
    header because that is where the API reads it: a key that is not scoped to a
    workspace is refused on every request that does not say which one to use.
    """
    args: dict[str, Any] = {"api_key": settings.anthropic_api_key.get_secret_value()}
    if settings.anthropic_workspace_id:
        args["default_headers"] = {WORKSPACE_HEADER: settings.anthropic_workspace_id}
    return args


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the SDK's failures into the two the retry loops understand.

    Raises:
        SchemaCallError: The answer did not fit the schema, or was cut off before
            it was complete. Both are things a repair turn can fix.
        ModelUnavailableError: The API refused the request. Transport failures
            are deliberately left to propagate -- a dropped connection is not
            something a repair prompt can fix either, but it is not a refusal.
    """
    try:
        yield
    except StructuredOutputException as error:
        raise SchemaCallError(str(error)) from error
    except MaxTokensReachedException as error:
        raise SchemaCallError(f"the response was cut off before it was complete: {error}") from error
    except APIStatusError as error:
        raise ModelUnavailableError(f"the API rejected the request: {error.message}") from error


class StrandsConversation:
    """A :class:`~extractors.conversation.StructuredConversation` backed by one Strands agent.

    The agent is held for the life of the conversation and no longer. Nothing
    here persists: there is no session manager, because the session file is the
    only state a conversation has and an agent with a memory of its own would be
    a second, unsynchronised copy of some of it.
    """

    def __init__(self, agent: "_TracedAgent") -> None:
        self._agent = agent

    def send(self, prompt: str, output: type[T]) -> T:
        """Send one turn and return the parsed answer.

        Raises:
            SchemaCallError: If the model failed to answer in the schema.
            ModelUnavailableError: If the API rejected the request.
        """
        return self._agent.ask(prompt, output)


class StrandsConversationFactory:
    """Opens Strands-backed conversations, choosing each role's model from the settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def open(self, role: str, system_prompt: str, cached_context: str | None = None) -> StrandsConversation:
        """Start a conversation for one agent.

        ``cached_context`` goes in as the opening exchange of the conversation
        rather than into the system prompt, ending in a cache point. That is not
        the obvious place, and the reason is the provider: Strands' Anthropic
        model sends the system prompt as a plain string, so a cache point placed
        there is dropped, while one inside a message is honoured. The effect is
        the same -- the block is the stable prefix of every request and is read
        from cache after the first.
        """
        model_id = self._settings.model_for(role)
        model = AnthropicModel(
            client_args=_client_args(self._settings),
            model_id=model_id,
            max_tokens=self._settings.max_tokens,
            # No temperature/top_p/top_k: the current Claude models reject them.
        )
        messages: list[Any] | None = None
        if cached_context:
            messages = [
                {"role": "user", "content": [{"text": cached_context}, {"cachePoint": {"type": "default"}}]},
                {"role": "assistant", "content": [{"text": "Understood. I have read the reference material."}]},
            ]
        return StrandsConversation(
            _TracedAgent(
                Agent(model=model, system_prompt=system_prompt, messages=messages, callback_handler=None),
                role=role,
                model_id=model_id,
                system_prompt=system_prompt,
                cached_context=cached_context,
            )
        )
