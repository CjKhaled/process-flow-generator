"""What to ask next, ranked by code.

The navigator chooses and words the questions, but it chooses from a list this
module has already put in order. Ranking is deterministic for the same reason the
ledger is: what matters most at a given point in a conversation should not depend
on a model's mood, and "why was that asked?" should have an answer one can read.

The order, most pressing first:

1. **Structural gaps in the current focus** -- a step whose outcome nobody
   stated, or one listing alternatives with no rule for choosing. These are holes
   in the flow the user can already see.
2. **Lanes and terms** -- the placeholder default lane if any step sits in it, a
   lane whose role is unknown, a term nobody explained. Cheap to answer, and they
   make everything asked afterwards land in the right place.
3. **Screening topics** whose program fact is still unknown: one answer can take
   several topics out of play.
4. **High-priority topics not yet covered** in the focus.
5. **Topics needing clarification** in the focus.
6. **Normal-priority gaps in the focus**, then **high-priority gaps elsewhere**.
7. **Everything else**: low priority, and other scopes' lesser topics.

Within a rank the order is the narrative's: checklist order for topics, graph
order for steps. Anything already asked twice without an answer is marked
``skip_offer`` and sinks to the bottom -- it is offered as something to skip,
never asked a third time.
"""

from dataclasses import dataclass

from ir.models import EdgeType, Node, NodeStatus
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, Priority, Topic, TopicStatus
from session.ledger import MAX_ASKS, node_key
from session.models import LaneStatus, LedgerEntry, QuestionKind, Role, Session

TOP = 8
"""How many candidates the navigator is shown."""

_GAP_STATUSES = frozenset({TopicStatus.NOT_YET_COVERED, TopicStatus.ASKED})


@dataclass(frozen=True)
class Candidate:
    """One thing worth asking, with why it is ranked where it is."""

    id: str
    rank: int
    kind: QuestionKind
    scope: str
    ask: str
    reason: str
    topic_ids: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()
    subject: str | None = None
    """The lane or term a lane or term question is about."""
    skip_offer: bool = False


def rank_candidates(session: Session, domain: DomainKnowledge) -> list[Candidate]:
    """Every candidate, most pressing first.

    Args:
        session: The session after this turn's statements and patch.
        domain: The knowledge base, for the checklist's questions and order.

    Returns:
        All candidates in rank order, each with an id (``c1``, ``c2``...) that is
        only meaningful within this list. The caller shows the navigator the
        first :data:`TOP`.
    """
    found = [
        *_structural(session),
        *_lanes_and_terms(session),
        *_topics(session, domain),
    ]
    # A stable sort, so within a rank the order each helper produced -- narrative
    # order -- is kept. Skip offers sink below everything that can still be asked.
    found.sort(key=lambda candidate: (candidate.skip_offer, candidate.rank))
    return [_with_id(candidate, index) for index, candidate in enumerate(found, start=1)]


def _with_id(candidate: Candidate, index: int) -> Candidate:
    return Candidate(**{**candidate.__dict__, "id": f"c{index}"})


def scope_of(node: Node) -> str:
    """The scope a node belongs to: its subprocess, or the main flow."""
    return node.subprocess or MAIN_SCOPE


def _times_asked(session: Session, node_id: str) -> int:
    """How often a question about this step has already been put to the user."""
    return sum(
        node_id in question.node_ids
        for message in session.transcript
        if message.role is Role.ASSISTANT
        for question in message.questions
    )


def _structural(session: Session) -> list[Candidate]:
    """Rank 1: open outcomes and unresolved alternatives in the focus scope."""
    by_id = {node.id: node for node in session.graph.nodes}
    accepted = set(session.accepted_open_items)
    found = []
    for node in session.graph.nodes:
        if scope_of(node) != session.focus or node_key(node.id) in accepted:
            continue
        skip = _times_asked(session, node.id) >= MAX_ASKS
        if node.status is NodeStatus.NEEDS_CLARIFICATION:
            branch = next(
                (edge for edge in session.graph.edges if edge.to_id == node.id and edge.type is EdgeType.BRANCH), None
            )
            if branch is not None and branch.from_id in by_id:
                ask = f"At the decision '{by_id[branch.from_id].label}', what happens when: {branch.condition}?"
                node_ids: tuple[str, ...] = (node.id, branch.from_id)
            else:
                ask = f"About the step '{node.label}': {node.detail or 'what happens here?'}"
                node_ids = (node.id,)
            found.append(
                Candidate(
                    id="",
                    rank=1,
                    kind=QuestionKind.STRUCTURAL,
                    scope=session.focus,
                    ask=ask,
                    reason=f"the flow has an open outcome here: {node.detail or node.label}",
                    node_ids=node_ids,
                    skip_offer=skip,
                )
            )
        elif node.alternatives:
            options = "; ".join(node.alternatives)
            found.append(
                Candidate(
                    id="",
                    rank=1,
                    kind=QuestionKind.STRUCTURAL,
                    scope=session.focus,
                    ask=f"At '{node.label}', what decides which of these happens: {options}?",
                    reason="the flow lists alternatives here with no rule for choosing between them",
                    node_ids=(node.id,),
                    skip_offer=skip,
                )
            )
    return found


def _lanes_and_terms(session: Session) -> list[Candidate]:
    """Rank 2: the placeholder lane if in use, lanes with no known role, unexplained terms."""
    found = []
    for lane in session.lanes:
        asked = sum(
            question.subject == lane.name
            for message in session.transcript
            for question in message.questions
            if question.kind is QuestionKind.LANE
        )
        if lane.status is LaneStatus.PLACEHOLDER:
            used = [node.id for node in session.graph.nodes if node.actor == lane.name]
            if used:
                found.append(
                    Candidate(
                        id="",
                        rank=2,
                        kind=QuestionKind.LANE,
                        scope=MAIN_SCOPE,
                        ask=(
                            "Some steps happen automatically, with nobody named as doing them. Which "
                            "system does that work, and what do you call it?"
                        ),
                        reason=f"{len(used)} step(s) sit in a placeholder lane because the system that does automated work has no name yet",
                        node_ids=tuple(used[:5]),
                        subject=lane.name,
                        skip_offer=asked >= MAX_ASKS,
                    )
                )
        elif lane.persona is None and lane.status is LaneStatus.PROPOSED:
            found.append(
                Candidate(
                    id="",
                    rank=2,
                    kind=QuestionKind.LANE,
                    scope=MAIN_SCOPE,
                    ask=f"What is '{lane.name}', and what part does it play in this process?",
                    reason=f"'{lane.name}' was named as doing work, but what kind of role or system it is was not clear",
                    subject=lane.name,
                    skip_offer=asked >= MAX_ASKS,
                )
            )
    found.extend(
        Candidate(
            id="",
            rank=2,
            kind=QuestionKind.TERM,
            scope=MAIN_SCOPE,
            ask=f"What does '{term.term}' mean here?",
            reason=f"'{term.term}' was used without being explained",
            subject=term.term,
            skip_offer=term.asked_count >= MAX_ASKS,
        )
        for term in session.unknown_terms
    )
    return found


def raised(session: Session, domain: DomainKnowledge, scope: str) -> bool:
    """Whether the conversation has reached a subprocess at all.

    Either the flow already has steps in it, or the user has spoken to a topic
    that hands off to it. Asking about the inside of a subprocess nobody has
    mentioned would be asking about another program's process.
    """
    if scope == MAIN_SCOPE:
        return True
    if any(node.subprocess == scope for node in session.graph.nodes):
        return True
    reached = {TopicStatus.PRESENT, TopicStatus.NEEDS_CLARIFICATION}
    return any(
        scope in topic.leads_to and (entry := session.entry(topic.id)) is not None and entry.status in reached
        for topic in domain.checklist.topics
    )


def _topics(session: Session, domain: DomainKnowledge) -> list[Candidate]:
    """Ranks 3 to 7: the checklist, in checklist order within each rank."""
    found = []
    for topic in domain.checklist.topics:
        entry = session.entry(topic.id)
        if entry is None:
            continue
        rank = _topic_rank(session, domain, topic, entry)
        if rank is None:
            continue
        found.append(
            Candidate(
                id="",
                rank=rank,
                kind=QuestionKind.SCREENING if rank == 3 else QuestionKind.GAP,
                scope=topic.scope,
                ask=topic.ask,
                reason=_reason(rank, topic, entry),
                topic_ids=(topic.id,),
                node_ids=entry.node_ids,
                follow_ups=topic.follow_ups,
                skip_offer=entry.asked_count >= MAX_ASKS,
            )
        )
    return found


def _topic_rank(session: Session, domain: DomainKnowledge, topic: Topic, entry: LedgerEntry) -> int | None:
    """Where one topic ranks, or None if it is not worth asking about now."""
    in_focus = topic.scope == session.focus
    gap = entry.status in _GAP_STATUSES
    if topic.screening and topic.sets_fact is not None:
        return 3 if gap and session.facts.get(topic.sets_fact) is None else None
    if entry.status is TopicStatus.NEEDS_CLARIFICATION:
        return 5 if in_focus else 7
    if not gap:
        return None
    if in_focus:
        return {Priority.HIGH: 4, Priority.NORMAL: 6, Priority.LOW: 7}[topic.priority]
    if topic.priority is Priority.HIGH and raised(session, domain, topic.scope):
        return 6
    return 7


def _reason(rank: int, topic: Topic, entry: LedgerEntry) -> str:
    if rank == 3:
        return "a screening question: the answer decides whether several other topics apply at all"
    if entry.status is TopicStatus.NEEDS_CLARIFICATION:
        return f"mentioned but unclear{': ' + entry.note if entry.note else ''}"
    return f"{topic.priority}-priority topic in '{topic.scope}', not covered yet"
