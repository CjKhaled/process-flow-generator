"""What each part of the graph *is* in BPMN, with no reference to geometry.

The mapping is mostly one-to-one, and the places it is not are the ones worth
knowing about:

* **Annotations are artifacts, not flow nodes.** A ``textAnnotation`` may not
  appear in a lane's ``flowNodeRef`` even though it is drawn inside the lane's
  band. Listing it there is the commonest way to make a file a modeller opens
  as empty.
* **Associations point the other way.** The IR runs its ``annotates`` edge from
  the annotation to the box it describes, because that is how the extractor
  thinks about it. BPMN runs the association from the annotated element to the
  annotation. The direction is flipped here, once.
* **A branch's answer, or failing that its condition, becomes the flow's name.**
  It is the label a reader sees on the arrow: ``Yes`` or ``No`` where the source
  asked a yes/no question, and the source's own wording where the decision has
  named outcomes instead. Either way it is deliberately not a
  ``conditionExpression``: that is an executable predicate, and these are
  sentences quoted from a source document.
* **A ``needs_clarification`` terminal is an ordinary end event.** Marking it up
  is stage 3's job; inventing a notation for it here would put a claim in the
  diagram that this stage cannot support.
* **Subprocesses collapse, and a collapsed box is where a path ends.** Every
  subprocess the skeleton declares is drawn as one box, the steps tagged with it
  are not drawn at all, and **nothing leaves the box for the main line**: a
  decision hands work off down a named path, and at this level of the diagram
  that path is over. So an edge running out of a subprocess is dropped, and
  anything only that edge led to goes with it -- an end state the subprocess
  reached, the rest of a branch it rejoined. Whatever is still reachable from the
  main line, such as a decision the subprocess happened to feed back into,
  survives untouched. The single exception is a hand-off from one box straight to
  another: a source that names a stretch of work and then names the next one is
  still speaking at the level the boxes are drawn at, and dropping the second
  would delete a named section of the process rather than fold it away.
  :func:`_collapse` works out the folding, :func:`_reachable` does the pruning,
  and :func:`element_ids` exposes the resulting map so stage 3 can still point an
  open question at the box that swallowed its step.

Every id is derived from the IR, never generated, so the same graph always
produces the same document. BPMN ids are ``xsd:ID``, so they are slugged to
NCNames -- which may not begin with a digit, and admit neither spaces nor most
punctuation.

**Emission order is the layout lever.** This stage computes no geometry; the
layouter does, and it breaks ties on BPMN declaration order. So the order things
are emitted in is the whole of our influence over the drawing: flow nodes go out
in the graph's own order -- which follows the source narrative -- with each
collapsed box standing where the first of its steps stood, and a gateway's
branches in ``Edge.order``. Shuffling either would redraw the diagram without
changing its meaning.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from ir.models import BranchAnswer, Edge, EdgeType, Node, NodeType, ProcessGraph
from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton, SubprocessSpec

_NOT_NAME_CHAR = re.compile(r"[^A-Za-z0-9_]")


class ElementKind(StrEnum):
    """The BPMN element a node becomes."""

    START_EVENT = "startEvent"
    END_EVENT = "endEvent"
    TASK = "task"
    EXCLUSIVE_GATEWAY = "exclusiveGateway"
    SUB_PROCESS = "subProcess"


_KIND_BY_NODE_TYPE: dict[NodeType, ElementKind] = {
    NodeType.START: ElementKind.START_EVENT,
    NodeType.TERMINAL: ElementKind.END_EVENT,
    NodeType.TASK: ElementKind.TASK,
    NodeType.GATEWAY: ElementKind.EXCLUSIVE_GATEWAY,
    NodeType.SUBPROCESS: ElementKind.SUB_PROCESS,
}


@dataclass(frozen=True)
class FlowNode:
    """One event, task, gateway or collapsed subprocess."""

    element_id: str
    node_id: str
    """The IR id, or the subprocess name for a box that stands for several nodes."""
    kind: ElementKind
    name: str
    actor: str
    """The lane this is drawn in: the node's own, or the subprocess's declared owner."""


@dataclass(frozen=True)
class TextAnnotation:
    """A note attached to a flow node. An artifact, not a flow node."""

    element_id: str
    node_id: str
    text: str


@dataclass(frozen=True)
class Lane:
    """One swimlane, and the flow nodes it owns."""

    element_id: str
    actor: str
    flow_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class SequenceFlow:
    """One connector in the control flow."""

    element_id: str
    edge_index: int
    source_id: str
    target_id: str
    name: str | None


@dataclass(frozen=True)
class Association:
    """The dashed connector from an annotated element to its annotation."""

    element_id: str
    edge_index: int
    source_id: str
    target_id: str


@dataclass(frozen=True)
class Definitions:
    """A whole BPMN document, still without coordinates."""

    process_name: str
    display_name: str
    collaboration_id: str
    participant_id: str
    process_id: str
    lanes: tuple[Lane, ...]
    flow_nodes: tuple[FlowNode, ...]
    annotations: tuple[TextAnnotation, ...]
    flows: tuple[SequenceFlow, ...]
    associations: tuple[Association, ...]


def ncname(text: str) -> str:
    """Slug text into a valid ``xsd:ID``.

    BPMN ids are NCNames: no spaces, no punctuation beyond the underscore, and
    never a leading digit. Actor names such as "SP Biologics" fail all three.

    Args:
        text: The raw name.

    Returns:
        A valid NCName. Deterministic, so the same input always yields the same id.
    """
    slug = _NOT_NAME_CHAR.sub("_", text)
    return slug if slug[:1].isalpha() or slug[:1] == "_" else f"_{slug}"


def node_element_id(node_id: str) -> str:
    """The BPMN id for an IR node."""
    return f"Node_{ncname(node_id)}"


def annotation_element_id(node_id: str) -> str:
    """The BPMN id for an annotation node.

    A prefix of its own, because the viewer restyles annotations -- bpmn-js draws
    one as an open bracket, and this project draws it as a box -- and CSS has no
    way to tell one shape from another except by id.
    """
    return f"Note_{ncname(node_id)}"


def lane_order(nodes: Sequence[Node], actors: Sequence[str], *, also: Collection[str] = ()) -> tuple[str, ...]:
    """The lanes to draw, top to bottom.

    Args:
        nodes: Every node in the graph, annotations included.
        actors: The declared actors, in ``metadata.yaml`` order.
        also: Further lanes something needs, whatever the nodes say. Collapsed
            subprocess boxes take their lane from the skeleton rather than from a
            node, so a lane can be needed that no *visible* node asks for.

    Returns:
        The declared actors that own at least one node, in declaration order.
        A declared actor no node is attributed to gets no lane, so listing one
        the source never uses costs nothing but an unused line of config.

    Raises:
        ValueError: If a node names an actor the process never declared. The
            stage-1 validator cannot catch this -- it has no ``ProcessConfig``,
            so it can only check that a lane was named, not that it exists --
            which makes this the first point the two can be compared.
    """
    used = {node.actor for node in nodes if node.actor} | set(also)
    unknown = sorted(used - set(actors))
    if unknown:
        known = ", ".join(actors) or "none are declared"
        raise ValueError(f"nodes are attributed to undeclared actor(s) {', '.join(unknown)}; declared actors: {known}")
    return tuple(actor for actor in actors if actor in used)


@dataclass(frozen=True)
class _Box:
    """One collapsed subprocess: the box drawn in place of its steps."""

    spec: SubprocessSpec
    element_id: str
    position: int
    """Where the first of its steps sat in the graph, which is where the box goes."""


@dataclass(frozen=True)
class _Collapse:
    """Which nodes survive as themselves, and what every IR id resolves to."""

    boxes: tuple[_Box, ...]
    element_of: Mapping[str, str]
    hidden: frozenset[str]
    """The ids folded into a box. Not drawn; their edges land on the box instead."""


@dataclass(frozen=True)
class _Drawing:
    """Everything a document holds except its lanes and the names built from config."""

    flow_nodes: tuple[FlowNode, ...]
    annotations: tuple[TextAnnotation, ...]
    flows: tuple[SequenceFlow, ...]
    associations: tuple[Association, ...]
    element_of: Mapping[str, str]
    """Every IR id, resolved to the element standing for it *on this diagram*."""


_DRAWN_ANYWAY = frozenset({NodeType.START})
"""Node types a collapse never swallows.

Only the start, and only because a process without a visible entry point is not
a process; one tagged into a subprocess is a tagging mistake, and showing it is
how that gets noticed. Everything else folds in, terminals included -- the box
itself is the end of the path, so an end state drawn beside it would be a second
ending for the same story.
"""


def element_ids(graph: ProcessGraph, skeleton: Skeleton) -> dict[str, str]:
    """Every IR node id, mapped to the BPMN element that stands for it.

    A node folded into a collapsed subprocess maps to that subprocess's box, and
    so does one the collapse stranded behind that box, so a caller holding IR ids
    -- a validation finding, say -- can still point at something the diagram
    actually contains.

    Args:
        graph: The graph stage 2 was given.
        skeleton: The subprocesses that collapse.

    Returns:
        IR node id -> BPMN element id, for every node in the graph.
    """
    return dict(_draw(graph, skeleton).element_of)


def _collapse(graph: ProcessGraph, skeleton: Skeleton) -> _Collapse:
    """Work out which subprocesses become a box, and what each id then resolves to.

    A subprocess the skeleton does not declare is left expanded. The validator
    already reports the node claiming it (``UNKNOWN_SUBPROCESS``), and folding it
    into a box named after a subprocess nobody declared would hide the same
    mistake twice.
    """
    boxes: list[_Box] = []
    hidden: dict[str, str] = {}
    for spec in skeleton.in_hint_order():
        members = [
            (index, node)
            for index, node in enumerate(graph.nodes)
            if node.subprocess == spec.name and node.type not in _DRAWN_ANYWAY
        ]
        if not members:
            continue
        element_id = f"Node_sub_{ncname(spec.name)}"
        boxes.append(_Box(spec=spec, element_id=element_id, position=members[0][0]))
        for _, node in members:
            hidden[node.id] = element_id

    return _Collapse(
        boxes=tuple(boxes),
        element_of={node.id: hidden.get(node.id) or _own_element_id(node) for node in graph.nodes},
        hidden=frozenset(hidden),
    )


def _own_element_id(node: Node) -> str:
    """The element a node becomes when nothing folds it away."""
    return annotation_element_id(node.id) if node.type is NodeType.ANNOTATION else node_element_id(node.id)


def _reachable(starts: Collection[str], flows: Sequence[SequenceFlow]) -> set[str]:
    """Every element still on a path from a start event.

    Run after the collapse has cut the flows leaving each box, which is the only
    thing that can strand an element: a graph reaching stage 2 has passed
    ``check_reachable_from_start``, so anything unreachable here was made so by
    the collapse and is part of the subprocess's aftermath rather than of the
    process the diagram is drawing.
    """
    successors: dict[str, list[str]] = {}
    for flow in flows:
        successors.setdefault(flow.source_id, []).append(flow.target_id)

    seen = set(starts)
    queue = list(starts)
    while queue:
        for target in successors.get(queue.pop(), ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def translate(graph: ProcessGraph, config: ProcessConfig, skeleton: Skeleton) -> Definitions:
    """Turn a process graph into BPMN elements.

    Args:
        graph: The graph from stage 1. Read for its nodes and edges only -- not
            for ``graph.process_name``, which is the model's own label for the
            graph and may disagree with the folder, since stage 1 warns about
            that rather than failing. Ids built from it would vary with the
            wording of a label.
        config: The process's ``metadata.yaml``. Supplies the machine name every
            id is built from, the pool's display name, and the actor order that
            becomes the lane order.
        skeleton: Supplies the subprocesses that collapse, and the lane each
            collapsed box is drawn in.

    Returns:
        The document's elements, ready to be written.

    Raises:
        ValueError: If a node, or a subprocess in the skeleton, names an actor
            ``metadata.yaml`` does not declare.
    """
    _check_skeleton_actors(skeleton, config)
    drawing = _draw(graph, skeleton)

    # Only lanes with something left in them. A lane whose every node was folded
    # into a box drawn elsewhere, or pruned away behind one, would otherwise
    # survive as an empty band -- the thing lane_order exists to avoid. Every
    # node is still passed to lane_order, hidden ones included, because an
    # invented actor is worth rejecting whether or not the node carrying it is
    # drawn.
    described = {item.node_id for item in drawing.annotations}
    drawn = {item.actor for item in drawing.flow_nodes if item.actor}
    drawn |= {node.actor for node in graph.nodes if node.id in described and node.actor}
    lanes = tuple(
        Lane(
            element_id=f"Lane_{ncname(actor)}",
            actor=actor,
            # Flow nodes only. A textAnnotation in here makes the file unopenable.
            flow_node_ids=tuple(item.element_id for item in drawing.flow_nodes if item.actor == actor),
        )
        for actor in lane_order(graph.nodes, tuple(config.actors), also=drawn)
        if actor in drawn
    )

    slug = ncname(config.process_name)
    return Definitions(
        process_name=config.process_name,
        display_name=config.display_name,
        collaboration_id=f"Collaboration_{slug}",
        participant_id=f"Participant_{slug}",
        process_id=f"Process_{slug}",
        lanes=lanes,
        flow_nodes=drawing.flow_nodes,
        annotations=drawing.annotations,
        flows=drawing.flows,
        associations=drawing.associations,
    )


def _draw(graph: ProcessGraph, skeleton: Skeleton) -> _Drawing:
    """Everything the document holds except its lanes and its names.

    Split out from :func:`translate` because :func:`element_ids` needs the same
    answer and has no ``ProcessConfig`` to give it -- and because the mapping it
    returns is only correct once the pruning has run, so re-deriving it from the
    collapse alone would quietly disagree with what was drawn.
    """
    collapse = _collapse(graph, skeleton)
    element_of = collapse.element_of

    placed: list[tuple[int, FlowNode]] = [
        (
            index,
            FlowNode(
                element_id=element_of[node.id],
                node_id=node.id,
                kind=_KIND_BY_NODE_TYPE[node.type],
                name=node.label,
                actor=node.actor or "",
            ),
        )
        for index, node in enumerate(graph.nodes)
        if node.id not in collapse.hidden and node.type is not NodeType.ANNOTATION
    ]
    placed += [
        (
            box.position,
            FlowNode(
                element_id=box.element_id,
                node_id=box.spec.name,
                kind=ElementKind.SUB_PROCESS,
                name=box.spec.label,
                actor=box.spec.actor,
            ),
        )
        for box in collapse.boxes
    ]
    candidates = tuple(item for _, item in sorted(placed, key=lambda pair: pair[0]))

    # An annotation folded into a box is dropped rather than re-pointed: a note
    # describing a step the diagram no longer shows has nothing to say about it.
    candidate_notes = tuple(
        TextAnnotation(element_id=element_of[node.id], node_id=node.id, text=node.label)
        for node in graph.nodes
        if node.id not in collapse.hidden and node.type is NodeType.ANNOTATION
    )

    known = {node.id for node in graph.nodes}
    annotation_ids = {item.node_id for item in candidate_notes}
    boxed = {box.element_id for box in collapse.boxes}
    flows: list[SequenceFlow] = []
    associations: list[Association] = []
    emitted: dict[tuple[str, str], int] = {}
    escapes: dict[str, list[str]] = {}
    for index, edge in _in_branch_order(graph, candidates, element_of):
        if edge.from_id not in known or edge.to_id not in known:
            continue
        source, target = element_of[edge.from_id], element_of[edge.to_id]
        if edge.type is EdgeType.ANNOTATES:
            if edge.from_id not in annotation_ids:
                continue
            associations.append(
                Association(
                    element_id=f"Association_{index}",
                    edge_index=index,
                    # Flipped: BPMN runs the association from the annotated
                    # element to the annotation, the IR runs it the other way.
                    source_id=target,
                    target_id=source,
                )
            )
        else:
            if source == target:
                continue  # Both ends folded into the same box: an internal step.
            if source in boxed and target not in boxed:
                # Nothing leaves a collapsed box for the main line: the path ends
                # there. Where it was going is remembered, because whatever that
                # strands belongs to this box and its open questions should still
                # point at it. A hand-off to another box is the one thing that
                # survives -- the source can name one stretch of work and then
                # name the next, and dropping the second would erase a section of
                # the process rather than fold it away.
                escapes.setdefault(source, []).append(target)
                continue
            name = _branch_name(edge) if edge.type is EdgeType.BRANCH else None
            folded = edge.from_id in collapse.hidden or edge.to_id in collapse.hidden
            already = emitted.get((source, target))
            if folded and already is not None:
                flows[already] = _merge(flows[already], name)
                continue
            emitted.setdefault((source, target), len(flows))
            flows.append(
                SequenceFlow(
                    element_id=f"Flow_{index}",
                    edge_index=index,
                    source_id=source,
                    target_id=target,
                    name=name,
                )
            )

    # Whatever the collapse stranded goes: the end state a subprocess reached,
    # the rest of a branch it rejoined. A graph with no start event is left
    # whole, since there is nothing to measure reachability from and dropping
    # everything would be a worse answer than drawing what there is.
    starts = {item.element_id for item in candidates if item.kind is ElementKind.START_EVENT}
    live = _reachable(starts, flows) if starts else {item.element_id for item in candidates}

    drawn_notes = tuple(
        item
        for item in candidate_notes
        if any(link.target_id == item.element_id for link in associations if link.source_id in live)
    )
    described = {item.element_id for item in drawn_notes}

    # A step the pruning removed is still somewhere -- inside whichever box's
    # exit stranded it -- and a question raised on it has to say so. Walked over
    # the flows as they were *before* the pruning, since the ones that reach a
    # stranded element are precisely the ones about to be thrown away. First box
    # to reach it wins, which is arbitrary only where two paths overlap, and
    # there either answer is as true as the other.
    stranded: dict[str, str] = {}
    for box in collapse.boxes:
        for reached in _reachable(escapes.get(box.element_id, ()), flows):
            if reached not in live:
                stranded.setdefault(reached, box.element_id)

    resolved = {node_id: stranded.get(element, element) for node_id, element in element_of.items()}
    # A note is drawn only when the box it describes is, so one left out follows
    # that box wherever it went rather than pointing at an element nobody drew.
    for edge in graph.edges:
        if edge.type is EdgeType.ANNOTATES and element_of.get(edge.from_id) not in described:
            resolved[edge.from_id] = resolved.get(edge.to_id, resolved.get(edge.from_id, ""))

    return _Drawing(
        flow_nodes=tuple(item for item in candidates if item.element_id in live),
        annotations=drawn_notes,
        flows=tuple(flow for flow in flows if flow.source_id in live and flow.target_id in live),
        associations=tuple(item for item in associations if item.source_id in live),
        element_of=resolved,
    )


def _check_skeleton_actors(skeleton: Skeleton, config: ProcessConfig) -> None:
    """Every subprocess is drawn in a lane the process declares.

    Checked for the whole skeleton rather than only the subprocesses this graph
    happens to contain: a lane named in config that does not exist is a config
    error whichever source text is being extracted, and finding it on the run
    that first mentions the subprocess would be finding it late.
    """
    unknown = sorted({spec.actor for spec in skeleton.subprocesses} - set(config.actors))
    if unknown:
        known = ", ".join(config.actors) or "none are declared"
        raise ValueError(
            f"the skeleton draws subprocess(es) in undeclared actor(s) {', '.join(unknown)}; declared actors: {known}"
        )


_ANSWER_WORDS: dict[BranchAnswer, str] = {BranchAnswer.YES: "Yes", BranchAnswer.NO: "No"}
"""What a yes/no answer is written as on the arrow. A drawing decision, so it lives here."""


def _branch_name(edge: Edge) -> str | None:
    """What a branch's arrow says.

    The answer where the source asked a yes/no question, and the source's own
    wording where it did not. A decision and two words beats a decision and two
    sentences, and the wording is not lost -- it stays in ``graph.json``, and in
    any finding raised against the branch.
    """
    return _ANSWER_WORDS[edge.answer] if edge.answer is not None else edge.condition


def _merge(flow: SequenceFlow, name: str | None) -> SequenceFlow:
    """Fold a second edge into a flow that already connects the same two elements.

    The label survives only if both edges agreed on it. Collapsing off-label
    review leaves three branches running from the box to the same next decision,
    each giving a different reason for getting there; picking one of the three to
    print on the arrow would be a claim about the process that nothing supports.
    """
    return flow if flow.name == name else replace(flow, name=None)


def _in_branch_order(
    graph: ProcessGraph, flow_nodes: Sequence[FlowNode], element_of: Mapping[str, str]
) -> list[tuple[int, Edge]]:
    """Edges in the order they should be declared, paired with their graph index.

    Sorted by where the source element was declared, then by ``Edge.order``. The
    second key is the one that matters: it is what makes a gateway's branches
    come out in the order the extractor chose, which decides which way each
    branch is drawn.

    Positions are keyed by BPMN element rather than by IR node, because several
    IR nodes can share one element once a subprocess has collapsed.

    The index is carried through because it is the edge's identity -- IR edges
    have none of their own -- and sorting would otherwise lose it.
    """
    position = {node.element_id: index for index, node in enumerate(flow_nodes)}
    last = len(position)
    return sorted(
        enumerate(graph.edges),
        key=lambda pair: (position.get(element_of.get(pair[1].from_id, ""), last), pair[1].order, pair[0]),
    )
