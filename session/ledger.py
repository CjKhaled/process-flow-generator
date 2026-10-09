"""The coverage ledger: which topics this conversation has settled.

One entry per checklist topic, initialised at session start and moved **only by
code**. The interpreter says what a message addressed; the functions here decide
what that does to a topic's status. No agent writes a status directly, which is
what keeps "covered" meaning the same thing on turn twenty as on turn two.

The transitions::

    not_yet_covered --asked--> asked --answered--> present | confirmed_absent
                                 |                  | needs_clarification | deferred
                                 +--not answered--> back where it was (asked_count kept)

    mentioned unprompted -----> present | needs_clarification
    needs_clarification, deferred --asked again--> asked --> ...
    program fact says no -----> not_applicable

**Silence is never absence.** A topic nobody answered goes back to where it was
with its ``asked_count`` kept, and that count is what stops a question being put
a third time.

Linking a topic to nodes is set arithmetic, not judgement: a topic rests on
statements, a node cites statements, and where the two share one the node is
linked. A topic the user covered that produced no node is reported, because it is
either something the extractor missed or something that is not a step.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ir.models import NodeOrigin, NodeStatus, NodeType, ProcessGraph
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, ProgramFact, TopicStatus
from session.models import AskedQuestion, LedgerEntry, Session
from validators.report import Finding, FindingCode

OPEN_STATUSES = frozenset({TopicStatus.NOT_YET_COVERED, TopicStatus.ASKED, TopicStatus.NEEDS_CLARIFICATION})
"""Statuses in which a topic still wants an answer."""

ANSWER_STATUSES = frozenset(
    {
        TopicStatus.PRESENT,
        TopicStatus.CONFIRMED_ABSENT,
        TopicStatus.NEEDS_CLARIFICATION,
        TopicStatus.DEFERRED,
    }
)
"""The only statuses a user's message can put a topic in."""

MAX_ASKS = 2
"""How often a topic is asked before it is only ever offered as something to skip."""


@dataclass(frozen=True)
class TopicUpdate:
    """What one message did to one topic, as the interpreter read it."""

    topic_id: str
    status: TopicStatus
    statement_ids: tuple[str, ...] = ()
    note: str | None = None


def initial_ledger(domain: DomainKnowledge) -> list[LedgerEntry]:
    """One untouched entry per topic, in checklist order.

    Every topic applies until a program fact says otherwise: an unknown fact
    never filters, so nothing is skipped on a guess.
    """
    return [
        LedgerEntry(topic_id=topic.id, scope=topic.scope, priority=topic.priority) for topic in domain.checklist.topics
    ]


def apply_updates(
    ledger: Sequence[LedgerEntry], updates: Iterable[TopicUpdate], asked: Iterable[AskedQuestion]
) -> list[LedgerEntry]:
    """Move topics according to what the user's message addressed.

    Args:
        ledger: The ledger before this message.
        updates: What the interpreter found. An update naming an unknown topic,
            or a status a message cannot produce, is ignored.
        asked: The questions that were pending when the message arrived. Any of
            their topics the message did not address falls back to where it was.

    Returns:
        The new ledger, in the same order.
    """
    by_topic = {update.topic_id: update for update in updates if update.status in ANSWER_STATUSES}
    was_asked = {topic_id for question in asked for topic_id in question.topic_ids}

    moved = []
    for entry in ledger:
        update = by_topic.get(entry.topic_id)
        if update is not None:
            moved.append(
                entry.model_copy(
                    update={
                        "status": update.status,
                        "evidence": tuple(dict.fromkeys((*entry.evidence, *update.statement_ids))),
                        "note": update.note,
                        "asked_from": None,
                    }
                )
            )
        elif entry.status is TopicStatus.ASKED and entry.topic_id in was_asked:
            moved.append(
                entry.model_copy(update={"status": entry.asked_from or TopicStatus.NOT_YET_COVERED, "asked_from": None})
            )
        else:
            moved.append(entry)
    return moved


def mark_asked(ledger: Sequence[LedgerEntry], questions: Iterable[AskedQuestion]) -> list[LedgerEntry]:
    """Record that these questions were put to the user.

    A topic already answered one way or the other is left alone: asking a
    follow-up about something present does not make it unanswered again.
    """
    asked = {topic_id for question in questions for topic_id in question.topic_ids}
    reaskable = OPEN_STATUSES | {TopicStatus.DEFERRED}
    return [
        entry.model_copy(
            update={
                "status": TopicStatus.ASKED,
                "asked_from": entry.asked_from if entry.status is TopicStatus.ASKED else entry.status,
                "asked_count": entry.asked_count + 1,
            }
        )
        if entry.topic_id in asked and entry.status in reaskable
        else entry
        for entry in ledger
    ]


def apply_applicability(
    ledger: Sequence[LedgerEntry], domain: DomainKnowledge, facts: dict[ProgramFact, bool | None]
) -> list[LedgerEntry]:
    """Switch topics off, or back on, according to what is now known.

    Two things take a topic out of play. A **program fact** the user has denied:
    no nurse program, so nothing about nurse enrollment. And a **subprocess the
    user has said does not exist**: when every topic that hands off to a
    subprocess is ``confirmed_absent``, the topics inside it have nothing to be
    about. An unknown fact, or a hand-off nobody has spoken to, never filters.

    Back on matters as much as off: a user who corrects "no nurse program" to
    "actually there is one" must get those topics back, untouched.
    """
    status_of = {entry.topic_id: entry.status for entry in ledger}
    closed_off = {
        sub.id
        for sub in domain.process.subprocesses
        if (gates := [topic.id for topic in domain.checklist.topics if sub.id in topic.leads_to])
        and all(status_of.get(gate) is TopicStatus.CONFIRMED_ABSENT for gate in gates)
    }

    moved = []
    for entry in ledger:
        topic = domain.topic(entry.topic_id)
        applies = (topic is None or topic.applies(facts)) and entry.scope not in closed_off
        if not applies and entry.status is not TopicStatus.NOT_APPLICABLE:
            moved.append(entry.model_copy(update={"status": TopicStatus.NOT_APPLICABLE, "asked_from": None}))
        elif applies and entry.status is TopicStatus.NOT_APPLICABLE:
            moved.append(entry.model_copy(update={"status": TopicStatus.NOT_YET_COVERED}))
        else:
            moved.append(entry)
    return moved


def link_nodes(ledger: Sequence[LedgerEntry], graph: ProcessGraph) -> list[LedgerEntry]:
    """Attach to each topic the nodes that rest on the same statements."""
    cited = {node.id: {ref.statement_id for ref in node.evidence} for node in graph.nodes}
    return [
        entry.model_copy(
            update={"node_ids": tuple(node_id for node_id, ids in cited.items() if ids.intersection(entry.evidence))}
        )
        for entry in ledger
    ]


def ledger_findings(
    ledger: Sequence[LedgerEntry], domain: DomainKnowledge, scope: str | None = None
) -> tuple[Finding, ...]:
    """What the ledger still holds open, as resolution findings.

    Args:
        ledger: The ledger, already linked to nodes.
        domain: Supplies topic titles and which priorities completion requires.
        scope: Restrict to one scope, or None for all of them.

    Returns:
        ``topic_without_nodes`` for a topic the user covered that no node rests
        on; ``open_topic`` for a required-priority topic never settled, and for
        any topic left needing clarification; ``deferred_topic`` for one the
        user put off. Lower-priority topics nobody reached are not reported: a
        list of everything that could have been asked is not a list of open
        questions.
    """
    required = set(domain.process.completion.scopes.required_priorities)
    findings = []
    for entry in ledger:
        if scope is not None and entry.scope != scope:
            continue
        topic = domain.topic(entry.topic_id)
        title = topic.title if topic else entry.topic_id
        if entry.status is TopicStatus.PRESENT and not entry.node_ids:
            findings.append(
                Finding.of(
                    FindingCode.TOPIC_WITHOUT_NODES,
                    f"'{title}' was described, but no step in the flow rests on what was said about it",
                )
            )
        elif entry.status is TopicStatus.DEFERRED:
            findings.append(
                Finding.of(FindingCode.DEFERRED_TOPIC, f"'{title}' was put off to check later", *entry.node_ids)
            )
        elif entry.status is TopicStatus.NEEDS_CLARIFICATION:
            detail = f": {entry.note}" if entry.note else ""
            findings.append(
                Finding.of(FindingCode.OPEN_TOPIC, f"'{title}' still needs clarifying{detail}", *entry.node_ids)
            )
        elif entry.status in OPEN_STATUSES and entry.priority in required:
            findings.append(Finding.of(FindingCode.OPEN_TOPIC, f"'{title}' was not covered"))
    return tuple(findings)


@dataclass(frozen=True)
class OpenItem:
    """One thing still open at close-out: a topic, or a step whose outcome nobody stated."""

    key: str
    scope: str
    kind: str
    """``topic`` or ``step``."""
    text: str
    topic_id: str | None = None
    node_id: str | None = None


def open_items(session: Session, domain: DomainKnowledge) -> tuple[OpenItem, ...]:
    """Everything the user has neither settled nor accepted, in scope order.

    The same rule :func:`ledger_findings` uses decides which topics count, so
    what the close-out view lists is what the final report will carry.
    """
    accepted = set(session.accepted_open_items)
    required = set(domain.process.completion.scopes.required_priorities)
    items = []
    for scope in domain.process.scopes:
        for node in session.graph.nodes:
            if (
                node.status is NodeStatus.NEEDS_CLARIFICATION
                and (node.subprocess or MAIN_SCOPE) == scope
                and node_key(node.id) not in accepted
            ):
                text = f"{node.label}: {node.detail}" if node.detail else node.label
                items.append(OpenItem(key=node_key(node.id), scope=scope, kind="step", text=text, node_id=node.id))
        for entry in session.ledger:
            if entry.scope != scope or topic_key(entry.topic_id) in accepted:
                continue
            topic = domain.topic(entry.topic_id)
            title = topic.title if topic else entry.topic_id
            if entry.status is TopicStatus.DEFERRED:
                text = f"{title} (to check later)"
            elif entry.status is TopicStatus.NEEDS_CLARIFICATION:
                text = f"{title} (needs clarifying{': ' + entry.note if entry.note else ''})"
            elif entry.status in OPEN_STATUSES and entry.priority in required:
                text = f"{title} (not covered)"
            else:
                continue
            items.append(
                OpenItem(key=topic_key(entry.topic_id), scope=scope, kind="topic", text=text, topic_id=entry.topic_id)
            )
    return tuple(items)


def rule_terminals(graph: ProcessGraph, scope: str) -> tuple[str, ...]:
    """The ids of the terminals standing in for outcomes the user never stated, in one scope."""
    return tuple(
        node.id
        for node in graph.nodes
        if node.type is NodeType.TERMINAL
        and node.origin is NodeOrigin.RULE
        and node.status is NodeStatus.NEEDS_CLARIFICATION
        and (node.subprocess or MAIN_SCOPE) == scope
    )


def topic_key(topic_id: str) -> str:
    """How an accepted topic is recorded in ``Session.accepted_open_items``."""
    return f"topic:{topic_id}"


def node_key(node_id: str) -> str:
    """How an accepted open terminal is recorded in ``Session.accepted_open_items``."""
    return f"node:{node_id}"


def scope_complete(session: Session, domain: DomainKnowledge, scope: str) -> bool:
    """Whether one scope is covered, by ``process.yaml``'s completion rules.

    Every applicable topic of a required priority has an accepted status, and --
    where the rules ask for it -- every rule terminal in the scope has been
    accepted by the user at close-out.
    """
    rules = domain.process.completion.scopes
    accepted = set(rules.accepted_statuses)
    for entry in session.ledger:
        if entry.scope == scope and entry.priority in rules.required_priorities and entry.status not in accepted:
            return False
    if rules.rule_terminals_must_be_accepted:
        done = set(session.accepted_open_items)
        return all(node_key(node_id) in done for node_id in rule_terminals(session.graph, scope))
    return True


def session_complete(session: Session, domain: DomainKnowledge) -> bool:
    """Whether every scope is covered."""
    return all(scope_complete(session, domain, scope) for scope in domain.process.scopes)


def coverage(session: Session, domain: DomainKnowledge) -> list[dict[str, object]]:
    """Per-scope progress, for the coverage panel and the CLI.

    Returns:
        One entry per scope, in process order: its label, counts by status, the
        topics still open (id, title, status, priority, note), and whether the
        scope is complete.
    """
    summary = []
    for scope in domain.process.scopes:
        entries = [entry for entry in session.ledger if entry.scope == scope]
        counts = Counter(entry.status.value for entry in entries)
        open_topics = [
            {
                "id": entry.topic_id,
                "title": topic.title if (topic := domain.topic(entry.topic_id)) else entry.topic_id,
                "status": entry.status.value,
                "priority": entry.priority.value,
                "note": entry.note,
            }
            for entry in entries
            if entry.status in OPEN_STATUSES or entry.status is TopicStatus.DEFERRED
        ]
        summary.append(
            {
                "scope": scope,
                "label": domain.process.scope_label(scope),
                "counts": dict(counts),
                "total": len(entries),
                "open_topics": open_topics,
                "complete": scope_complete(session, domain, scope),
            }
        )
    return summary
