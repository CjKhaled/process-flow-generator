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
from utils.settings import Settings


class StrandsModelCall:
    """A :class:`~extractors.process.ModelCall` backed by a Strands agent.

    The agent is held across calls on purpose: a repair turn continues the same
    conversation, so the model sees its own previous graph next to the critique
    rather than re-extracting from scratch.
    """

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    def __call__(self, prompt: str) -> ProcessGraph:
        """Send one turn and return the parsed graph.

        Raises:
            SchemaCallError: If the model failed to produce a graph in the schema.
                Transport and API failures are deliberately left to propagate --
                a rate limit is not something a repair prompt can fix.
        """
        with _translated():
            result = self._agent(prompt, structured_output_model=ProcessGraph)

        graph = result.structured_output
        if not isinstance(graph, ProcessGraph):
            raise SchemaCallError(f"expected a ProcessGraph, got {type(graph).__name__}")
        return graph


def build_model_call(settings: Settings, config: ProcessConfig, skeleton: Skeleton) -> StrandsModelCall:
    """Build the callable the extraction loop drives.

    Args:
        settings: Global settings supplying credentials and model defaults.
        config: Per-process settings, which may override the model.
        skeleton: The subprocesses this process is expected to contain.

    Returns:
        A model call wrapping an agent primed with the extraction system prompt.
    """
    model = AnthropicModel(
        client_args={"api_key": settings.anthropic_api_key.get_secret_value()},
        model_id=config.model_id or settings.model_id,
        max_tokens=settings.max_tokens,
        # No temperature/top_p/top_k: the current Claude models reject them.
    )
    return StrandsModelCall(Agent(model=model, system_prompt=build_system_prompt(config, skeleton)))


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

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    def send(self, prompt: str, output: type[T]) -> T:
        """Send one turn and return the parsed answer.

        Raises:
            SchemaCallError: If the model failed to answer in the schema.
            ModelUnavailableError: If the API rejected the request.
        """
        with _translated():
            result = self._agent(prompt, structured_output_model=output)

        answer: BaseModel | None = result.structured_output
        if not isinstance(answer, output):
            raise SchemaCallError(f"expected a {output.__name__}, got {type(answer).__name__}")
        return answer


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
        model = AnthropicModel(
            client_args={"api_key": self._settings.anthropic_api_key.get_secret_value()},
            model_id=self._settings.model_for(role),
            max_tokens=self._settings.max_tokens,
            # No temperature/top_p/top_k: the current Claude models reject them.
        )
        messages: list[Any] | None = None
        if cached_context:
            messages = [
                {"role": "user", "content": [{"text": cached_context}, {"cachePoint": {"type": "default"}}]},
                {"role": "assistant", "content": [{"text": "Understood. I have read the reference material."}]},
            ]
        # No callback handler: the default one prints the model's output to stdout,
        # which is wrong for a server and would interleave with the CLI's own.
        return StrandsConversation(
            Agent(model=model, system_prompt=system_prompt, messages=messages, callback_handler=None)
        )
