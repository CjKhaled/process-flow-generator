"""What the page draws while the conversation is running: the live views.

Rebuilt from the session on every request, never stored. A view is a pure
function of the master graph, so it cannot fall out of step with it -- there is
nothing to keep in sync.

Two kinds, from the one graph:

* **The main view**: the master graph with each subprocess that has steps drawn
  as a single box (``sub:<id>``). Unlike stage 2's fold, edges *leaving* a box
  are kept, so the summary reads as one line from start to finish. Stage 2 drops
  them because a BPMN reader opens the subprocess's own diagram to see where it
  goes; here the box is a tab away and a main flow that stopped dead at every
  hand-off would say less.
* **A view per subprocess**: its slice, exactly as close-out will draw it.

Annotations are not drawn in either. A note is a fact about a step, and the live
view has a side panel for those, so each becomes a line in the rationale of the
step it describes.

**Rationale** is what makes the flow auditable: for every step, the exact words
it came from, which turn they were said in, what is still open about it, and
which coverage topics it bears on. The quotes are the ones the evidence check
already verified against the statements, so the panel cannot show a quote the
user did not say.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from ir.models import BranchAnswer, Edge, EdgeType, Node, NodeStatus, NodeType, ProcessGraph
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, SubprocessDef
from session.models import Session, StatementOrigin
from session.slicing import handoff_lane, members, slice_subprocess

BOX_PREFIX = "sub:"

_ANSWER_WORDS = {BranchAnswer.YES: "Yes", BranchAnswer.NO: "No"}


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ViewNode(_View):
    """One shape in a live view."""

    id: str
    kind: str
    """``start``, ``task``, ``gateway``, ``terminal`` or ``subprocess``."""
    label: str
    lane: str | None
    status: str
    origin: str
    open_question: bool
    from_answer: bool
    """Whether any of its evidence came from an answer, not the first description."""
    subprocess_id: str | None = None
    """Set on a collapsed box: the subprocess it opens."""


class ViewEdge(_View):
    """One arrow in a live view."""

    id: str
    source: str
    target: str
    label: str | None


class EvidenceLine(_View):
    """One quote, with the statement it was taken from."""

    statement_id: str
    quote: str
    statement_text: str
    restatement: str | None
    turn: int
    origin: str


class Rationale(_View):
    """Why a step is in the flow, and what is still open about it."""

    label: str
    kind: str
    lane: str | None
    status: str
    origin: str
    detail: str | None = None
    open_question: str | None = None
    evidence: tuple[EvidenceLine, ...] = ()
    alternatives: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    entry: str | None = None
    """A collapsed box: what hands work into the subprocess."""
    step_count: int | None = None
    open_count: int | None = None


class FlowView(_View):
    """One tab of the page: a flow, and the rationale for everything in it."""

    id: str
    label: str
    nodes: tuple[ViewNode, ...]
    edges: tuple[ViewEdge, ...]
    rationale: dict[str, Rationale]


def session_views(session: Session, domain: DomainKnowledge) -> list[FlowView]:
    """Every view of a session: the main flow, then each subprocess that has steps.

    Args:
        session: The session.
        domain: The knowledge base, for subprocess labels and topic titles.

    Returns:
        The views in tab order. Empty before the first turn has produced a graph.
    """
    if not session.graph.nodes:
        return []
    views = [main_view(session, domain)]
    for sub in domain.process.subprocesses:
        sliced = slice_subprocess(session.graph, sub, domain.process)
        if sliced is not None:
            views.append(_flow_view(sub.id, sub.label, sliced, session, domain, boxes={}))
    return views


def main_view(session: Session, domain: DomainKnowledge) -> FlowView:
    """The master graph with each subprocess that has steps collapsed into one box."""
    boxes = {sub.id: sub for sub in domain.process.subprocesses if members(session.graph, sub.id)}
    return _flow_view(MAIN_SCOPE, domain.process.scope_label(MAIN_SCOPE), session.graph, session, domain, boxes=boxes)


def _flow_view(
    view_id: str,
    label: str,
    graph: ProcessGraph,
    session: Session,
    domain: DomainKnowledge,
    *,
    boxes: Mapping[str, SubprocessDef],
) -> FlowView:
    """Draw one graph, folding the given subprocesses into boxes."""
    folded = {node.id: f"{BOX_PREFIX}{sub_id}" for sub_id in boxes for node in members(graph, sub_id)}
    notes = _notes(graph)
    answered = {s.id for s in session.corpus if s.origin is StatementOrigin.ANSWER}

    nodes: list[ViewNode] = []
    rationale: dict[str, Rationale] = {}
    for node in graph.nodes:
        if node.type is NodeType.ANNOTATION:
            continue
        box_id = folded.get(node.id)
        if box_id is None:
            nodes.append(_view_node(node, answered))
            rationale[node.id] = _rationale(node, session, domain, notes.get(node.id, ()))
        elif box_id not in rationale:
            sub = boxes[box_id.removeprefix(BOX_PREFIX)]
            inside = members(graph, sub.id)
            open_count = sum(item.status is NodeStatus.NEEDS_CLARIFICATION for item in inside)
            lane = handoff_lane(session, domain.process, sub)
            status = NodeStatus.NEEDS_CLARIFICATION if open_count else NodeStatus.STATED
            nodes.append(
                ViewNode(
                    id=box_id,
                    kind="subprocess",
                    label=sub.label,
                    lane=lane,
                    status=status,
                    origin="source",
                    open_question=bool(open_count),
                    from_answer=any(ref.statement_id in answered for item in inside for ref in item.evidence),
                    subprocess_id=sub.id,
                )
            )
            rationale[box_id] = Rationale(
                label=sub.label,
                kind="subprocess",
                lane=lane,
                status=status,
                origin="source",
                entry=sub.entry,
                step_count=len(inside),
                open_count=open_count,
            )

    return FlowView(id=view_id, label=label, nodes=tuple(nodes), edges=_edges(graph, folded), rationale=rationale)


def _edges(graph: ProcessGraph, folded: Mapping[str, str]) -> tuple[ViewEdge, ...]:
    """The flow's arrows, re-pointed at boxes and de-duplicated.

    Several steps of a subprocess can lead to the same next step, which after
    folding is several arrows between the same two shapes. They are drawn as
    one, and it keeps a label only if they all agreed on it -- the same rule
    stage 2 uses, for the same reason: picking one of three reasons to print
    would be a claim nothing supports.
    """
    drawn = {node.id for node in graph.nodes if node.type is not NodeType.ANNOTATION}
    merged: dict[tuple[str, str], str | None] = {}
    for edge in sorted(graph.edges, key=lambda item: item.order):
        if edge.type is EdgeType.ANNOTATES or edge.from_id not in drawn or edge.to_id not in drawn:
            continue
        ends = (folded.get(edge.from_id, edge.from_id), folded.get(edge.to_id, edge.to_id))
        if ends[0] == ends[1]:
            continue  # Both ends inside the same box: an internal step.
        label = _edge_label(edge)
        merged[ends] = label if ends not in merged or merged[ends] == label else None
    return tuple(
        ViewEdge(id=f"e{index}", source=source, target=target, label=label)
        for index, ((source, target), label) in enumerate(merged.items())
    )


def _edge_label(edge: Edge) -> str | None:
    """What an arrow says: the answer, failing that the condition, failing that nothing."""
    if edge.answer is not None:
        return _ANSWER_WORDS[edge.answer]
    return edge.condition


def _notes(graph: ProcessGraph) -> dict[str, tuple[str, ...]]:
    """Each annotation's text, keyed by the step it describes."""
    text = {node.id: node.label for node in graph.nodes if node.type is NodeType.ANNOTATION}
    found: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.type is EdgeType.ANNOTATES and edge.from_id in text:
            found.setdefault(edge.to_id, []).append(text[edge.from_id])
    return {node_id: tuple(lines) for node_id, lines in found.items()}


def _view_node(node: Node, answered: set[str]) -> ViewNode:
    return ViewNode(
        id=node.id,
        kind=node.type.value,
        label=node.label,
        lane=node.actor,
        status=node.status.value,
        origin=node.origin.value,
        open_question=node.status is NodeStatus.NEEDS_CLARIFICATION,
        from_answer=any(ref.statement_id in answered for ref in node.evidence),
    )


def _rationale(node: Node, session: Session, domain: DomainKnowledge, notes: Sequence[str]) -> Rationale:
    evidence = []
    for ref in node.evidence:
        statement = session.statement(ref.statement_id)
        if statement is not None:
            evidence.append(
                EvidenceLine(
                    statement_id=statement.id,
                    quote=ref.quote,
                    statement_text=statement.raw_text,
                    restatement=statement.restatement,
                    turn=statement.turn,
                    origin=statement.origin.value,
                )
            )
    topics = tuple(
        topic.title
        for entry in session.ledger
        if node.id in entry.node_ids and (topic := domain.topic(entry.topic_id)) is not None
    )
    is_open = node.status is NodeStatus.NEEDS_CLARIFICATION
    return Rationale(
        label=node.label,
        kind=node.type.value,
        lane=node.actor,
        status=node.status.value,
        origin=node.origin.value,
        detail=node.detail,
        open_question=node.detail if is_open else None,
        evidence=tuple(evidence),
        alternatives=node.alternatives,
        notes=tuple(notes),
        topics=topics,
    )
