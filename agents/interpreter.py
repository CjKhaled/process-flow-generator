"""The interpreter: what did the user just say, in relation to what was asked?

One fresh conversation per turn, and the narrowest job of the three agents. It
never sees the graph and cannot change it. It reads one message -- or, on the
first turn, the description's statements -- against the pending questions and the
open topics, and reports what the message addressed: which topics, which lanes,
which facts, which earlier statements it corrects.

Its output is a *reading*, not a decision. Every status change, every lane and
every fact it reports is applied by code in :mod:`session.orchestrator`, which is
free to ignore what does not hold up (a persona that does not exist, a topic that
is not in the checklist).

It is the agent that can run on a faster, cheaper model
(``PFG_INTERPRETER_MODEL_ID``), because it reads one message, not a process.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.prompts import load_prompt
from extractors.conversation import INTERPRETER, ConversationFactory
from extractors.errors import SchemaCallError
from knowledge.compose import interpreter_context
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, ProgramFact
from session.models import Session

AnswerStatus = Literal["present", "confirmed_absent", "needs_clarification", "deferred"]
"""The statuses a message can put a topic in. The rest belong to code."""

MAX_ATTEMPTS = 2
"""One repair turn for an answer that did not fit the schema, then the turn is rejected."""


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class InterpretedStatement(_Out):
    """One thing the user said, placed."""

    index: int = Field(
        ge=1,
        description=(
            "The statement's number. For a first description, the number the prompt gave it. For "
            "an answer, its position among the statements you split the message into, from 1."
        ),
    )
    raw_text: str = Field(
        default="",
        description=(
            "For an answer: the statement's words, copied exactly from the user's message. For a "
            "first description, whose statements are already split: leave empty."
        ),
    )
    restatement: str | None = Field(
        default=None,
        description=(
            "The answer folded into its question so it reads on its own, containing only facts "
            "the answer states or explicitly affirms. Null when the statement is already a "
            "complete sentence, and always null for a first description."
        ),
    )
    question_id: str | None = Field(default=None, description="The id of the pending question this answers, or null.")
    topic_ids: tuple[str, ...] = Field(
        default=(), description="Ids of the coverage topics this statement actually addresses."
    )
    scope: str = Field(
        default=MAIN_SCOPE,
        description="'main', a subprocess id, or 'unknown' when it cannot be told which part this is about.",
    )


class TopicReading(_Out):
    """What the message did to one coverage topic."""

    topic_id: str = Field(min_length=1, description="A topic id from the prompt's list.")
    status: AnswerStatus = Field(
        description=(
            "present: the user described it. confirmed_absent: the user said it does not happen. "
            "deferred: the user does not know or will check. needs_clarification: mentioned, but "
            "vague, partial or contradictory."
        )
    )
    statement_refs: tuple[int, ...] = Field(default=(), description="The index of each supporting statement.")
    note: str | None = Field(default=None, description="For needs_clarification: what is unclear.")


class Correction(_Out):
    """The user contradicting or withdrawing something said earlier."""

    statement_refs: tuple[int, ...] = Field(description="The index of each statement making the correction.")
    description: str = Field(min_length=1, description="What was said before and what is said now, in plain words.")


class NewLane(_Out):
    """A name the user attributes work to, not yet in the lane list."""

    name: str = Field(min_length=1, description="Exactly as the user writes it.")
    persona: str | None = Field(default=None, description="A persona id from the prompt's list, or null if unclear.")
    description: str = Field(default="", description="Only what the user said about it. May be empty.")
    statement_refs: tuple[int, ...] = Field(default=(), description="The index of each statement naming it.")


class LaneUpdate(_Out):
    """Something new about a lane already in the list."""

    name: str = Field(min_length=1, description="The lane's name, exactly as listed.")
    persona: str | None = Field(default=None, description="A persona id, or null to leave it as it is.")
    description: str | None = Field(default=None, description="What the user added, or null.")
    statement_refs: tuple[int, ...] = ()


class DefaultLane(_Out):
    """The user naming the system that does the program's automated work."""

    name: str = Field(min_length=1, description="The system's name, exactly as the user writes it.")
    statement_refs: tuple[int, ...] = ()


class TermLearned(_Out):
    """Shorthand whose meaning the user's own words make clear."""

    term: str = Field(min_length=1)
    meaning: str = Field(min_length=1, description="In the user's terms. Never a guess.")
    statement_refs: tuple[int, ...] = ()


class TermUnknown(_Out):
    """Shorthand the user used without the text making its meaning clear."""

    term: str = Field(min_length=1)
    statement_ref: int = Field(ge=1, description="The index of the statement it first appears in.")


class FactReading(_Out):
    """A program fact the user stated or confirmed."""

    fact: ProgramFact
    value: bool
    statement_refs: tuple[int, ...] = ()


class InterpretResult(_Out):
    """What one message means, in relation to what was asked."""

    statements: tuple[InterpretedStatement, ...] = Field(
        default=(), description="The statements, placed. See the instructions for the two cases."
    )
    topic_updates: tuple[TopicReading, ...] = Field(
        default=(), description="Only topics the message actually addresses. Silence is not absence."
    )
    corrections: tuple[Correction, ...] = ()
    new_lanes: tuple[NewLane, ...] = ()
    lane_updates: tuple[LaneUpdate, ...] = ()
    default_lane: DefaultLane | None = None
    learned_terms: tuple[TermLearned, ...] = ()
    unknown_terms: tuple[TermUnknown, ...] = ()
    facts: tuple[FactReading, ...] = Field(default=(), description="Only facts the user stated or confirmed.")
    focus_request: str | None = Field(
        default=None, description="'main' or a subprocess id when the user asks to discuss that part; else null."
    )
    meta: Literal["done", "pause", "question_for_system"] | None = None


def interpret(
    session: Session,
    domain: DomainKnowledge,
    *,
    conversations: ConversationFactory,
    statements: tuple[str, ...] = (),
    message: str | None = None,
    hint: str | None = None,
) -> InterpretResult:
    """Read one message, or the first description, against the session.

    Args:
        session: The session as it stood before the message. Not modified.
        domain: The knowledge base, for the topic, persona and glossary lists.
        conversations: Where the model comes from.
        statements: The first description, already split. Given on turn 1 only.
        message: The user's answer. Given on every later turn.
        hint: What a quick reply means, when the message was one.

    Returns:
        The interpreter's reading.

    Raises:
        extractors.errors.SchemaCallError: If no attempt answered in the schema.
        extractors.errors.ModelUnavailableError: If the API rejected the request.
    """
    system_prompt = load_prompt("interpreter", domain.process.display_name)
    conversation = conversations.open(INTERPRETER, system_prompt)
    prompt = build_prompt(session, domain, statements=statements, message=message, hint=hint)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return conversation.send(prompt, InterpretResult)
        except SchemaCallError as error:
            if attempt == MAX_ATTEMPTS:
                raise
            prompt = (
                "That response did not fit the schema. The validator reported:\n\n"
                f"{error}\n\nReturn it again, correcting that and changing nothing else."
            )
    raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover


def build_prompt(
    session: Session,
    domain: DomainKnowledge,
    *,
    statements: tuple[str, ...] = (),
    message: str | None = None,
    hint: str | None = None,
) -> str:
    """Build the interpreter's user turn. Pure, so what the agent is shown can be asserted."""
    sections = [interpreter_context(domain, session), _lanes(session), _unknown_terms(session)]
    sections.append(f"## Current focus\n\n{session.focus}")

    if statements:
        listed = "\n".join(f"[{index}] {text}" for index, text in enumerate(statements, start=1))
        sections.append(
            "## The user's first description\n\n"
            "Already split into numbered statements. Classify them by number; do not rewrite them.\n\n"
            f"<statements>\n{listed}\n</statements>"
        )
    else:
        sections.append(_pending(session))
        note = f"\n\n(The user pressed a quick reply. It means: {hint})" if hint else ""
        sections.append(f"## The user's message\n\n<message>\n{(message or '').strip()}\n</message>{note}")
    return "\n\n".join(section for section in sections if section)


def _lanes(session: Session) -> str:
    listed = "\n".join(
        f"- **{lane.name}** (persona: {lane.persona or 'not known'}; {lane.status})"
        + (f" -- {lane.description}" if lane.description else "")
        for lane in session.lanes
    )
    return f"## Lanes learned so far\n\n{listed}\n\nUnattributed work currently goes to **{session.default_lane}**."


def _unknown_terms(session: Session) -> str:
    if not session.unknown_terms:
        return ""
    return "## Terms not yet explained\n\n" + "\n".join(f"- {item.term}" for item in session.unknown_terms)


def _pending(session: Session) -> str:
    if not session.pending:
        return "## Pending questions\n\nNone."
    labels = {node.id: node.label for node in session.graph.nodes}
    lines = []
    for question in session.pending:
        about = []
        if question.topic_ids:
            about.append("topics: " + ", ".join(question.topic_ids))
        if question.node_ids:
            about.append("steps: " + ", ".join(f"{labels.get(n, n)} ({n})" for n in question.node_ids))
        if question.subject:
            about.append(f"about: {question.subject}")
        lines.append(f"- `{question.id}` [{question.kind}; {'; '.join(about) or 'general'}] {question.text}")
    return "## Pending questions\n\nThe questions the user was last asked.\n\n" + "\n".join(lines)
