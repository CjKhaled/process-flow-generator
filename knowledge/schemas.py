"""The shape of every file in ``domain_knowledge/``.

The knowledge base is data a domain expert edits, so each YAML file has a model
here and each model forbids extra keys: a misspelt field is a load failure, not a
question that silently never gets asked.

These models are **shape-only**, for the same reason the IR's are. What the files
must agree on between themselves -- a topic's ``leads_to`` naming a real
subprocess, each program fact having exactly one screening topic -- is checked by
``tests/test_domain_knowledge.py`` over the files as they are committed, because
those are properties of the knowledge base, not of any one record in it.
"""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAIN_SCOPE = "main"
"""The scope of everything that belongs to no subprocess."""


class ProgramFact(StrEnum):
    """What a session can learn about the program that switches topics on or off.

    Four, and closed: a fact is only useful if some topic's ``applies_when`` reads
    it and some screening topic's ``sets_fact`` settles it, so adding one is a
    change to the checklist and to this enum together.
    """

    HAS_REMS = "product.has_rems"
    HAS_NURSE_PROGRAM = "program.has_nurse_program"
    PATIENT_SELF_ENROLLMENT = "program.patient_self_enrollment"
    PEDIATRIC_POPULATION = "product.pediatric_population"


class Priority(StrEnum):
    """How much a topic matters to calling a scope covered."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TopicStatus(StrEnum):
    """Where one coverage topic stands in a session.

    Defined here rather than beside the ledger because ``process.yaml`` names
    these values itself, in ``completion.scopes.accepted_statuses``.
    """

    NOT_YET_COVERED = "not_yet_covered"
    ASKED = "asked"
    PRESENT = "present"
    CONFIRMED_ABSENT = "confirmed_absent"
    NEEDS_CLARIFICATION = "needs_clarification"
    DEFERRED = "deferred"
    NOT_APPLICABLE = "not_applicable"


FactCondition = dict[ProgramFact, bool]
"""Program facts and the value each must have, e.g. ``{product.has_rems: true}``."""


class _Record(BaseModel):
    """Every knowledge record: immutable, and strict about its keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Persona(_Record):
    """A lane archetype: a responsibility, not a job title."""

    name: str = Field(min_length=1)
    lane_description: str = Field(min_length=1)
    responsibilities: tuple[str, ...] = ()
    common_titles: tuple[str, ...] = ()
    overlaps_with: tuple[str, ...] = ()
    assignment_hints: tuple[str, ...] = ()
    applies_when: FactCondition | None = None


class PersonasFile(_Record):
    """``agnostic/personas.yaml``."""

    schema_version: int
    personas: dict[str, Persona]


class GlossaryCategory(StrEnum):
    """What kind of thing a glossary term names."""

    PROCESS = "process"
    COVERAGE = "coverage"
    CLINICAL = "clinical"
    CONSENT = "consent"
    RECORD = "record"
    PLATFORM = "platform"
    DOCUMENT = "document"
    REGULATORY = "regulatory"


class GlossaryTerm(_Record):
    """One piece of domain shorthand that is not an actor."""

    meaning: str = Field(min_length=1)
    category: GlossaryCategory
    aliases: tuple[str, ...] = ()


class GlossaryFile(_Record):
    """``agnostic/glossary.yaml``."""

    schema_version: int
    terms: dict[str, GlossaryTerm]


class Scope(_Record):
    """Where a process begins and ends, and what it does and does not include."""

    starts_at: str = Field(min_length=1)
    ends_at: tuple[str, ...]
    in_scope: tuple[str, ...] = ()
    out_of_scope: tuple[str, ...] = ()


class ExitKind(StrEnum):
    """Where a subprocess's outcome leads."""

    RETURN = "return"
    """Back to the main flow."""

    BOUNDARY = "boundary"
    """Out of the process, at one of its declared boundaries."""


class SubprocessExit(_Record):
    """One outcome a subprocess returns with."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: ExitKind


class SubprocessDef(_Record):
    """A subprocess that should exist: tagged on the master graph, one box on the main flow."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    knowledge: str = Field(min_length=1)
    entry: str = Field(min_length=1)
    exits: tuple[SubprocessExit, ...]


class BoundaryKind(StrEnum):
    """What reaching a boundary means for the case."""

    HANDOFF = "handoff"
    TERMINAL = "terminal"


class Boundary(_Record):
    """A canonical end point, shared with neighbouring processes."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: BoundaryKind
    next_process: str | None = None
    note: str | None = None


class ScopeCompletion(_Record):
    """When one scope -- the main flow, or one subprocess -- counts as covered."""

    required_priorities: tuple[Priority, ...]
    accepted_statuses: tuple[TopicStatus, ...]
    rule_terminals_must_be_accepted: bool


class SessionCompletion(_Record):
    """When the whole session may close."""

    require_all_scopes_complete: bool
    user_may_close_early: bool


class Completion(_Record):
    """The completion rules of ``process.yaml``."""

    scopes: ScopeCompletion
    session: SessionCompletion


class ProcessFile(_Record):
    """``<process>/process.yaml``: scope, subprocesses, boundaries and completion."""

    schema_version: int
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scope: Scope
    default_persona: str = Field(min_length=1)
    typical_personas: tuple[str, ...]
    subprocesses: tuple[SubprocessDef, ...]
    boundaries: tuple[Boundary, ...]
    completion: Completion

    @property
    def subprocess_ids(self) -> tuple[str, ...]:
        """The declared subprocess ids, in declaration order."""
        return tuple(item.id for item in self.subprocesses)

    @property
    def scopes(self) -> tuple[str, ...]:
        """Every scope a topic or a node can belong to: the main flow, then each subprocess."""
        return (MAIN_SCOPE, *self.subprocess_ids)

    def subprocess(self, subprocess_id: str) -> SubprocessDef | None:
        """The subprocess with this id, or None if the process declares no such one."""
        return next((item for item in self.subprocesses if item.id == subprocess_id), None)

    def scope_label(self, scope: str) -> str:
        """What to call a scope when speaking to a person."""
        found = self.subprocess(scope)
        return found.label if found is not None else "Main flow"


class Topic(_Record):
    """One coverage topic: something a complete description of the process would settle."""

    id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    area: str = Field(min_length=1)
    title: str = Field(min_length=1)
    priority: Priority
    applies_when: Literal["always"] | FactCondition
    screening: bool = False
    sets_fact: ProgramFact | None = None
    cues: tuple[str, ...] = ()
    ask: str = Field(min_length=1)
    follow_ups: tuple[str, ...] = ()
    leads_to: tuple[str, ...] = ()

    @field_validator("leads_to", mode="before")
    @classmethod
    def _one_or_many(cls, value: object) -> object:
        """The file writes a single hand-off as a bare string and several as a list."""
        return (value,) if isinstance(value, str) else value

    def applies(self, facts: dict[ProgramFact, bool | None]) -> bool:
        """Whether this topic is still worth asking about, given what is known.

        An unknown fact never filters: a topic is dropped only once the user has
        said the thing it depends on is not so.
        """
        if self.applies_when == "always":
            return True
        return all(facts.get(fact) is None or facts.get(fact) == wanted for fact, wanted in self.applies_when.items())


class ChecklistFile(_Record):
    """``<process>/checklist.yaml``."""

    schema_version: int
    process: str = Field(min_length=1)
    topics: tuple[Topic, ...]


class FrontMatter(_Record):
    """The YAML header of a markdown knowledge file."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    owner: str | None = None
    last_reviewed: date | None = None
