"""The navigator: what to ask next, where to focus, and what to say.

The only agent that reads the knowledge base, and the only one that speaks to the
user. It cannot edit the graph: its output is a reply, up to three questions and
a proposed focus, and nothing in :mod:`session.orchestrator` routes any of that
into the flow. That separation is the point. Knowing how programs usually run is
what makes a question good, and it is exactly what must not leak into a diagram
of how *this* one runs.

Its reference material -- every knowledge file and the whole checklist -- is the
same text on every turn, so it is passed as the conversation's cached context
rather than rebuilt into the prompt. What changes each turn is small: a summary
of the flow, the ledger, and the candidates code has already ranked.

It is given a summary of the graph, not the graph. Raw JSON would invite it to
reason about ids and edges; what it needs is what a person would see.

No ``get_node`` tool. Mixing tool use with structured output in one call is a
risk this stage has no need to take: the summary already carries each open
step's detail, which is what the tool would have been asked for.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.prompts import load_prompt
from extractors.conversation import NAVIGATOR, ConversationFactory
from ir.models import EdgeType, NodeStatus, NodeType, ProcessGraph
from knowledge.compose import navigator_knowledge
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, TopicStatus
from session.candidates import Candidate, scope_of
from session.ledger import OpenItem, coverage
from session.models import Phase, Session
from validators.report import Finding

TRANSCRIPT_TAIL = 6
"""How many of the latest transcript lines the navigator is shown."""


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NavigatorQuestion(_Out):
    """One question to put to the user."""

    candidate_id: str | None = Field(
        default=None,
        description="The id of the candidate this came from, e.g. 'c2'. Null only for a question of your own.",
    )
    kind: Literal["gap", "structural", "lane", "term", "screening", "suggested"] = Field(
        description="Copied from the candidate. 'suggested' for a question of your own."
    )
    topic_ids: tuple[str, ...] = Field(default=(), description="Copied from the candidate, or merged from two.")
    node_ids: tuple[str, ...] = Field(default=(), description="Copied from the candidate.")
    scope: str = Field(default=MAIN_SCOPE, description="Copied from the candidate: 'main' or a subprocess id.")
    text: str = Field(min_length=1, description="The question as the user reads it. Open, never leading.")


class NavigatorResult(_Out):
    """The navigator's turn."""

    focus: str = Field(description="'main' or a subprocess id: where the conversation should be focused next.")
    questions: tuple[NavigatorQuestion, ...] = Field(
        default=(), description="One to three questions. None only when closing."
    )
    reply: str = Field(
        min_length=1,
        description="The message shown to the user, without the questions: the page shows those separately.",
    )
    propose_close: bool = Field(
        default=False, description="True when nothing important remains and the session could be finished."
    )


def navigate(
    session: Session,
    domain: DomainKnowledge,
    candidates: Sequence[Candidate],
    *,
    conversations: ConversationFactory,
    findings: Sequence[Finding] = (),
    open_items: Sequence[OpenItem] = (),
    meta: str | None = None,
) -> NavigatorResult:
    """Ask the navigator for this turn's reply and questions.

    Args:
        session: The session after this turn's statements and patch. Not modified.
        domain: The knowledge base.
        candidates: The candidates to choose from, already ranked and cut.
        conversations: Where the model comes from.
        findings: This turn's resolution findings.
        open_items: What is still open, when the session is closing.
        meta: The interpreter's reading of a message about the session itself.

    Returns:
        The navigator's answer, as the model gave it. The caller checks it.

    Raises:
        extractors.errors.SchemaCallError: If the answer did not fit the schema.
        extractors.errors.ModelUnavailableError: If the API rejected the request.
    """
    conversation = conversations.open(
        NAVIGATOR,
        load_prompt("navigator", domain.process.display_name),
        cached_context=navigator_knowledge(domain),
    )
    prompt = build_prompt(session, domain, candidates, findings=findings, open_items=open_items, meta=meta)
    return conversation.send(prompt, NavigatorResult)


def build_prompt(
    session: Session,
    domain: DomainKnowledge,
    candidates: Sequence[Candidate],
    *,
    findings: Sequence[Finding] = (),
    open_items: Sequence[OpenItem] = (),
    meta: str | None = None,
) -> str:
    """Build the navigator's user turn. Pure, so what it is shown can be asserted."""
    process = domain.process
    sections = [
        f"## Where the conversation is\n\nPhase: {session.phase}. Turn: {session.turn}. "
        f"Focus: {session.focus} ({process.scope_label(session.focus)}).",
    ]
    if not session.flow_updated:
        sections.append(
            "## The flow was not updated this turn\n\n"
            "The user's last answer was kept, but it could not be applied to the flow. It will be "
            "applied on the next turn. Say this plainly."
        )
    if meta == "question_for_system":
        sections.append("## Note\n\nThe user's last message asked about the session itself. Answer it briefly first.")

    sections.append("## The flow so far\n\n" + graph_summary(session.graph, domain))
    if findings:
        sections.append(
            "## Open points raised this turn\n\n" + "\n".join(f"- {finding.message}" for finding in findings)
        )
    sections.append("## Coverage\n\n" + _coverage(session, domain))
    sections.append(_facts(session))
    sections.append(_lanes(session))

    if session.phase is Phase.CLOSING:
        listed = "\n".join(f"- [{process.scope_label(item.scope)}] {item.text}" for item in open_items) or "- Nothing."
        sections.append(
            "## The session is closing\n\nList these open items in your reply, grouped by flow, one line "
            f"each, and ask whether the user wants to answer any of them or finish.\n\n{listed}"
        )
    else:
        sections.append("## Candidates, ranked\n\n" + (_candidates(candidates) or "None. Consider proposing to close."))

    tail = session.transcript[-TRANSCRIPT_TAIL:]
    sections.append(
        "## Recent conversation\n\n"
        + "\n".join(f"{message.role}: {message.text}" + _shown(message.questions) for message in tail)
    )
    return "\n\n".join(sections)


def _shown(questions: Sequence[object]) -> str:
    return "".join(f"\n  (asked) {getattr(question, 'text', '')}" for question in questions)


def graph_summary(graph: ProcessGraph, domain: DomainKnowledge) -> str:
    """The flow as a person would read it, one scope at a time.

    Steps with their lane, decisions with their branches, and every open point
    with what is open about it. Ids are included because questions refer to
    steps by them, but nothing here is JSON.
    """
    if not graph.nodes:
        return "Nothing yet."
    labels = {node.id: node.label for node in graph.nodes}
    parts = []
    for scope in domain.process.scopes:
        nodes = [node for node in graph.nodes if scope_of(node) == scope]
        if not nodes:
            continue
        lines = [f"### {domain.process.scope_label(scope)}"]
        for node in nodes:
            if node.type is NodeType.ANNOTATION:
                target = next((e.to_id for e in graph.edges if e.from_id == node.id), None)
                lines.append(f"- note on '{labels.get(target or '', '?')}': {node.label}")
                continue
            line = f"- [{node.type}] {node.label} ({node.id}; lane: {node.actor})"
            if node.status is NodeStatus.NEEDS_CLARIFICATION:
                line += f" -- OPEN: {node.detail}"
            if node.alternatives:
                line += f" -- alternatives with no rule: {'; '.join(node.alternatives)}"
            lines.append(line)
            if node.type is NodeType.GATEWAY:
                for edge in sorted((e for e in graph.edges if e.from_id == node.id), key=lambda e: e.order):
                    if edge.type is EdgeType.BRANCH:
                        lines.append(f"    - if {edge.condition} -> {labels.get(edge.to_id, edge.to_id)}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _coverage(session: Session, domain: DomainKnowledge) -> str:
    lines = []
    for scope in coverage(session, domain):
        counts = scope["counts"]
        assert isinstance(counts, dict)
        done = sum(count for status, count in counts.items() if status not in _STILL_OPEN)
        lines.append(f"- {scope['label']}: {done} of {scope['total']} topics settled")
    return "\n".join(lines)


_STILL_OPEN = frozenset(
    {TopicStatus.NOT_YET_COVERED.value, TopicStatus.ASKED.value, TopicStatus.NEEDS_CLARIFICATION.value}
)


def _facts(session: Session) -> str:
    words = {True: "yes", False: "no", None: "not known"}
    return "## Program facts\n\n" + "\n".join(
        f"- {fact.value}: {words[value]}" for fact, value in session.facts.items()
    )


def _lanes(session: Session) -> str:
    lanes = "\n".join(f"- {lane.name} ({lane.persona or 'role not known'}; {lane.status})" for lane in session.lanes)
    terms = ", ".join(term.term for term in session.unknown_terms) or "none"
    return f"## Lanes and terms\n\n{lanes}\n\nDefault lane: {session.default_lane}. Unexplained terms: {terms}."


def _candidates(candidates: Sequence[Candidate]) -> str:
    blocks = []
    for candidate in candidates:
        lines = [
            f"- id: {candidate.id} | kind: {candidate.kind} | scope: {candidate.scope}"
            + (" | skip_offer" if candidate.skip_offer else ""),
            f"  ask: {candidate.ask}",
            f"  why: {candidate.reason}",
        ]
        if candidate.topic_ids:
            lines.append(f"  topic_ids: {', '.join(candidate.topic_ids)}")
        if candidate.node_ids:
            lines.append(f"  node_ids: {', '.join(candidate.node_ids)}")
        if candidate.follow_ups:
            lines.append(f"  follow-ups: {' / '.join(candidate.follow_ups)}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
