"""The seam every conversational agent talks to a model through.

:class:`~extractors.process.ModelCall` serves the one-shot extraction: one prompt
in, one :class:`~ir.models.ProcessGraph` out, system prompt fixed when it is
built. The conversation has three agents with three output types, so this is the
same idea made general -- and, like ``ModelCall``, it imports no SDK. Agents
depend on these protocols; :mod:`extractors.model` implements them with Strands;
tests implement them with a list of canned answers. That is the whole reason a
session can be run end to end with no key and no network.

The failure contract is the one the extraction loop already relies on, from
:mod:`extractors.errors`: :class:`~extractors.errors.SchemaCallError` for a
response that did not fit the schema, which a repair turn can fix, and
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
