"""The seam every agent talks to a model through.

Three agents, three output types, one way to reach a model -- and no SDK import
here. Agents depend on these protocols; :mod:`extractors.model` implements them
with Strands; tests implement them with a list of canned answers. That is the
whole reason a session can be run end to end with no key and no network.

The failure contract is in :mod:`extractors.errors`:
:class:`~extractors.errors.SchemaCallError` for a response that did not fit the
schema, which a repair turn can fix, and
:class:`~extractors.errors.ModelUnavailableError` for a request the API refused,
which nothing in a prompt can.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

INTERPRETER = "interpreter"
EXTRACTOR = "extractor"
NAVIGATOR = "navigator"


class StructuredConversation(Protocol):
    """One conversation with a model, answering in a schema.

    Stateful across calls: a second :meth:`send` continues the same
    conversation, so a repair turn is read next to the answer it corrects.
    """

    def send(self, prompt: str, output: type[T]) -> T:
        """Send one turn and return the parsed answer.

        Args:
            prompt: The user turn.
            output: The model the answer must validate as.

        Returns:
            A validated instance of ``output``.

        Raises:
            extractors.errors.SchemaCallError: If the answer did not fit ``output``.
            extractors.errors.ModelUnavailableError: If the API rejected the request.
        """
        ...


class ConversationFactory(Protocol):
    """Opens conversations. One is opened per agent per turn, and none outlives its turn."""

    def open(self, role: str, system_prompt: str, cached_context: str | None = None) -> StructuredConversation:
        """Start a conversation.

        Args:
            role: Which agent this is for -- ``interpreter``, ``extractor`` or
                ``navigator`` -- which decides the model it runs on.
            system_prompt: The agent's instructions.
            cached_context: A large block that is the same on every turn, placed
                where the provider can cache it. The navigator's domain
                knowledge is the case it exists for.

        Returns:
            A conversation with nothing said in it yet.
        """
        ...
