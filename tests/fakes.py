"""Stand-ins for the model, so a whole session runs with no key and no network.

Every agent reaches a model through :class:`extractors.conversation.ConversationFactory`,
so one fake of that protocol is enough to drive the interpreter, the extractor and
the navigator together through the real pipeline, the real validators and the
real ledger. What is faked is only the thing this project does not own.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import BaseModel

from extractors.conversation import EXTRACTOR, INTERPRETER, NAVIGATOR, T

Scripted = BaseModel | Exception


@dataclass
class FakeConversation:
    """One conversation, answering from its role's shared script."""

    role: str
    owner: "FakeConversations"

    def send(self, prompt: str, output: type[T]) -> T:
        self.owner.prompts[self.role].append(prompt)
        script = self.owner.scripts[self.role]
        if not script:
            raise AssertionError(f"the fake {self.role} was called more times than it was scripted for")
        response = script.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, output), f"the {self.role} script holds a {type(response).__name__}"
        return response


@dataclass
class FakeConversations:
    """A scripted :class:`~extractors.conversation.ConversationFactory`.

    Answers are queued per role and handed out in order, across conversations:
    a repair turn and the next turn's first call simply take the next one.
    """

    scripts: dict[str, list[Scripted]] = field(default_factory=lambda: defaultdict(list))
    prompts: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    system_prompts: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    cached: dict[str, list[str | None]] = field(default_factory=lambda: defaultdict(list))

    def open(self, role: str, system_prompt: str, cached_context: str | None = None) -> FakeConversation:
        self.system_prompts[role].append(system_prompt)
        self.cached[role].append(cached_context)
        return FakeConversation(role=role, owner=self)

    def interpreter(self, *responses: Scripted) -> "FakeConversations":
        self.scripts[INTERPRETER].extend(responses)
        return self

    def extractor(self, *responses: Scripted) -> "FakeConversations":
        self.scripts[EXTRACTOR].extend(responses)
        return self

    def navigator(self, *responses: Scripted) -> "FakeConversations":
        self.scripts[NAVIGATOR].extend(responses)
        return self

    def calls(self, role: str) -> int:
        return len(self.prompts[role])
