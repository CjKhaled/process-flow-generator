"""The Strands adapter: the only place in the project that talks to an LLM.

Everything the SDK knows is confined here. :mod:`extractors.process` depends on
the :class:`~extractors.process.ModelCall` protocol instead, which is what lets
the retry loop be tested without a network.
"""

from anthropic import APIStatusError
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands.types.exceptions import MaxTokensReachedException, StructuredOutputException

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
        try:
            result = self._agent(prompt, structured_output_model=ProcessGraph)
        except StructuredOutputException as error:
            raise SchemaCallError(str(error)) from error
        except MaxTokensReachedException as error:
            raise SchemaCallError(f"the response was cut off before the graph was complete: {error}") from error
        except APIStatusError as error:
            raise ModelUnavailableError(f"the API rejected the request: {error.message}") from error

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
