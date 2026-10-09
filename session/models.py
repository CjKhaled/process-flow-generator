"""The state of one conversation.

**Code owns state.** Everything a conversation knows -- what was said, which
topics are covered, which lanes exist, where the discussion is focused, the graph
itself -- lives in a :class:`Session`, and no agent's memory of earlier turns is
relied on for any of it. Each agent is built fresh every turn and handed what it
needs from here. That is what makes a session inspectable (it is one JSON file),
replayable, and safe to resume in a process that has never seen it before.

The records inside a session are frozen; the session itself is not. A turn works
on a deep copy and the copy replaces the original only if the turn succeeds, so
"reject the turn, no state change" is a matter of throwing the copy away.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ir.models import ProcessGraph
from knowledge.schemas import MAIN_SCOPE, Priority, ProgramFact, TopicStatus
from session.patch import GraphPatch
from validators.report import Finding

SCHEMA_VERSION = 1

PLACEHOLDER_LANE = "System (unconfirmed)"
"""The default lane before the user has named the system that does automated work.

Named so that it reads as a question when it shows up on a step.
"""

UNKNOWN_SCOPE = "unknown"
"""The scope of a statement that could not be placed in the main flow or a subprocess."""


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Phase(StrEnum):
    """Where the conversation as a whole has got to."""

    DESCRIBING = "describing"
    PROBING = "probing"
    CLOSING = "closing"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


class TurnStatus(StrEnum):
    """What the turn in flight is doing, or how the last one ended."""

    IDLE = "idle"
    QUEUED = "queued"
    INTERPRETING = "interpreting"
    EXTRACTING = "extracting"
    NAVIGATING = "navigating"
    FINALISING = "finalising"
    FAILED = "failed"


class StatementOrigin(StrEnum):
    """Whether a statement came from the first description or from an answer."""

    INITIAL_DESCRIPTION = "initial_description"
    ANSWER = "answer"


class Statement(_Record):
    """One thing the user said. The unit every node and branch cites."""

    id: str = Field(min_length=1)
    origin: StatementOrigin
    turn: int = Field(ge=1)
    raw_text: str = Field(min_length=1)
    restatement: str | None = None
    """The answer folded into its question, so it reads on its own. Never adds a fact."""
    question_id: str | None = None
    topic_ids: tuple[str, ...] = ()
    scope: str = MAIN_SCOPE


class LaneStatus(StrEnum):
    """How firmly a lane is established."""

    PLACEHOLDER = "placeholder"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class SessionLane(_Record):
    """A swimlane this session has learned, in the user's own name for it."""

    name: str = Field(min_length=1)
    persona: str | None = None
    description: str = ""
    evidence: tuple[str, ...] = ()
    status: LaneStatus = LaneStatus.PROPOSED


class LearnedTerm(_Record):
    """Shorthand the user explained. Kept in the session, never written to the knowledge base."""

    term: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()


class UnknownTerm(_Record):
    """Shorthand the user used without explaining, which is worth asking about."""

    term: str = Field(min_length=1)
    first_statement_id: str = Field(min_length=1)
    asked_count: int = Field(default=0, ge=0)


class LedgerEntry(_Record):
    """One coverage topic's standing in this session."""

    topic_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    priority: Priority
    status: TopicStatus = TopicStatus.NOT_YET_COVERED
    evidence: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()
    asked_count: int = Field(default=0, ge=0)
    asked_from: TopicStatus | None = None
    """What the topic was before it was last asked about, to fall back to if nobody answers."""
    note: str | None = None


class QuestionKind(StrEnum):
    """Why a question is being asked."""

    GAP = "gap"
    STRUCTURAL = "structural"
    LANE = "lane"
    TERM = "term"
    SCREENING = "screening"
    SUGGESTED = "suggested"


class AskedQuestion(_Record):
    """A question put to the user, with what it was about."""

    id: str = Field(min_length=1)
    turn: int = Field(ge=1)
    kind: QuestionKind
    topic_ids: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()
    scope: str = MAIN_SCOPE
    text: str = Field(min_length=1)
    subject: str | None = None
    """The lane or term a lane or term question is about."""


class Role(StrEnum):
    """Who said a line of the transcript."""

    USER = "user"
    ASSISTANT = "assistant"


class Message(_Record):
    """One line of the transcript."""

    role: Role
    text: str
    turn: int = Field(ge=1)
    questions: tuple[AskedQuestion, ...] = ()
    """The questions shown under an assistant message."""


class StepTiming(_Record):
    """How long one step of a turn took, so a slow turn can be diagnosed."""

    step: str
    attempt: int = Field(default=1, ge=1)
    seconds: float = Field(ge=0)


class GraphVersion(_Record):
    """What one turn did to the graph."""

    turn: int = Field(ge=1)
    patch: GraphPatch | None = None
    """The patch that was applied, or None when the turn left the graph as it was."""
    updated: bool = True
    """False when extraction ran out of attempts and the previous graph was kept."""
    attempts: int = Field(default=0, ge=0)
    structural: tuple[Finding, ...] = ()
    """The defects of the last rejected attempt, when the turn kept the previous graph."""
    resolution: tuple[Finding, ...] = ()
    timings: tuple[StepTiming, ...] = ()


def _now() -> datetime:
    return datetime.now(UTC)


class Session(BaseModel):
    """One conversation about one process, start to finish."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    process_id: str = Field(min_length=1)
    schema_version: int = SCHEMA_VERSION
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    phase: Phase = Phase.DESCRIBING
    focus: str = MAIN_SCOPE
    requested_focus: str | None = None
    """A scope the user opened in the page, honoured on the next turn."""
    turn: int = Field(default=0, ge=0)
    turn_status: TurnStatus = TurnStatus.IDLE
    turn_error: str | None = None

    corpus: list[Statement] = Field(default_factory=list)
    transcript: list[Message] = Field(default_factory=list)
    lanes: list[SessionLane] = Field(default_factory=list)
    default_lane: str = PLACEHOLDER_LANE
    """The lane unattributed work goes to. One of ``lanes``, always."""
    glossary: list[LearnedTerm] = Field(default_factory=list)
    unknown_terms: list[UnknownTerm] = Field(default_factory=list)
    facts: dict[ProgramFact, bool | None] = Field(default_factory=lambda: dict.fromkeys(ProgramFact))

    graph: ProcessGraph
    versions: list[GraphVersion] = Field(default_factory=list)
    ledger: list[LedgerEntry] = Field(default_factory=list)
    pending: list[AskedQuestion] = Field(default_factory=list)
    question_count: int = Field(default=0, ge=0)
    """How many questions have ever been asked, which is what keeps their ids unique."""
    retry_statement_ids: list[str] = Field(default_factory=list)
    accepted_open_items: list[str] = Field(default_factory=list)

    def lane(self, name: str) -> SessionLane | None:
        """The lane with this name, or None."""
        return next((lane for lane in self.lanes if lane.name == name), None)

    def statement(self, statement_id: str) -> Statement | None:
        """The statement with this id, or None."""
        return next((item for item in self.corpus if item.id == statement_id), None)

    def entry(self, topic_id: str) -> LedgerEntry | None:
        """The ledger entry for a topic, or None."""
        return next((item for item in self.ledger if item.topic_id == topic_id), None)

    @property
    def flow_updated(self) -> bool:
        """Whether the last turn changed the flow, or had to leave it as it was."""
        return self.versions[-1].updated if self.versions else True
