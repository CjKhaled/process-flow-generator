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
* **A branch's condition becomes the flow's name.** It is the label a reader
  sees on the arrow. It is deliberately not a ``conditionExpression``: that is
  an executable predicate, and these are sentences quoted from a source document.
* **A ``needs_clarification`` terminal is an ordinary end event.** Marking it up
  is stage 3's job; inventing a notation for it here would put a claim in the
  diagram that this stage cannot support.

Every id is derived from the IR, never generated, so the same graph always
produces the same document. BPMN ids are ``xsd:ID``, so they are slugged to
NCNames -- which may not begin with a digit, and admit neither spaces nor most
punctuation.

**Emission order is the layout lever.** This stage computes no geometry; the
layouter does, and it breaks ties on BPMN declaration order. So the order things
are emitted in is the whole of our influence over the drawing: flow nodes go out
in the skeleton's subprocess order, and a gateway's branches in ``Edge.order``.
Shuffling either would redraw the diagram without changing its meaning.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ir.models import Edge, EdgeType, Node, NodeType, ProcessGraph
from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton

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
    """The IR id, which is how the layout's box is found again."""
    kind: ElementKind
    name: str


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


def lane_order(nodes: Sequence[Node], actors: Sequence[str]) -> tuple[str, ...]:
    """The lanes to draw, top to bottom.

    Args:
        nodes: Every node in the graph, annotations included.
        actors: The declared actors, in ``metadata.yaml`` order.

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
    used = {node.actor for node in nodes if node.actor}
    unknown = sorted(used - set(actors))
    if unknown:
        known = ", ".join(actors) or "none are declared"
        raise ValueError(f"nodes are attributed to undeclared actor(s) {', '.join(unknown)}; declared actors: {known}")
    return tuple(actor for actor in actors if actor in used)


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
        skeleton: Supplies the subprocess order flow nodes are emitted in.

    Returns:
        The document's elements, ready to be written.

    Raises:
        ValueError: If a node names an actor ``metadata.yaml`` does not declare.
    """
    ordered_nodes = _in_subprocess_order(graph, skeleton)
    flow_nodes = tuple(
        FlowNode(
            element_id=node_element_id(node.id),
            node_id=node.id,
            kind=_KIND_BY_NODE_TYPE[node.type],
            name=node.label,
        )
        for node in ordered_nodes
        if node.type is not NodeType.ANNOTATION
    )
    annotations = tuple(
        TextAnnotation(element_id=node_element_id(node.id), node_id=node.id, text=node.label)
        for node in ordered_nodes
        if node.type is NodeType.ANNOTATION
    )

    lane_of = {node.id: node.actor for node in graph.nodes}
    lanes = tuple(
        Lane(
            element_id=f"Lane_{ncname(actor)}",
            actor=actor,
            # Flow nodes only. A textAnnotation in here makes the file unopenable.
            flow_node_ids=tuple(item.element_id for item in flow_nodes if lane_of[item.node_id] == actor),
        )
        for actor in lane_order(graph.nodes, tuple(config.actors))
    )

    known = {node.id for node in graph.nodes}
    annotation_ids = {item.node_id for item in annotations}
    flows: list[SequenceFlow] = []
    associations: list[Association] = []
    for index, edge in _in_branch_order(graph, flow_nodes):
        if edge.from_id not in known or edge.to_id not in known:
            continue
        if edge.type is EdgeType.ANNOTATES:
            if edge.from_id not in annotation_ids:
                continue
            associations.append(
                Association(
                    element_id=f"Association_{index}",
                    edge_index=index,
                    # Flipped: BPMN runs the association from the annotated
                    # element to the annotation, the IR runs it the other way.
                    source_id=node_element_id(edge.to_id),
                    target_id=node_element_id(edge.from_id),
                )
            )
        else:
            flows.append(
                SequenceFlow(
                    element_id=f"Flow_{index}",
                    edge_index=index,
                    source_id=node_element_id(edge.from_id),
                    target_id=node_element_id(edge.to_id),
                    name=edge.condition if edge.type is EdgeType.BRANCH else None,
                )
            )

    slug = ncname(config.process_name)
    return Definitions(
        process_name=config.process_name,
        display_name=config.display_name,
        collaboration_id=f"Collaboration_{slug}",
        participant_id=f"Participant_{slug}",
        process_id=f"Process_{slug}",
        lanes=lanes,
        flow_nodes=flow_nodes,
        annotations=annotations,
        flows=tuple(flows),
        associations=tuple(associations),
    )


def _in_subprocess_order(graph: ProcessGraph, skeleton: Skeleton) -> tuple[Node, ...]:
    """Nodes in the order they should be declared.

    The layouter has no `partition` option; declaration order is what it breaks
    ties on. Emitting the skeleton's subprocesses in ``order_hint`` order is
    therefore how intake ends up drawn before onboarding.

    A node claiming no subprocess, or one the skeleton does not declare, sorts
    last rather than first: the skeleton describes the expected spine, so
    anything outside it is an addendum to the diagram rather than its opening.
    Ties keep the graph's own order, so the result is a stable sort of a stable
    input.
    """
    rank = {spec.name: position for position, spec in enumerate(skeleton.in_hint_order())}
    unplaced = len(rank)
    return tuple(sorted(graph.nodes, key=lambda node: rank.get(node.subprocess or "", unplaced)))


def _in_branch_order(graph: ProcessGraph, flow_nodes: Sequence[FlowNode]) -> list[tuple[int, Edge]]:
    """Edges in the order they should be declared, paired with their graph index.

    Sorted by where the source node was declared, then by ``Edge.order``. The
    second key is the one that matters: it is what makes a gateway's branches
    come out in the order the extractor chose, which decides which way each
    branch is drawn.

    The index is carried through because it is the edge's identity -- IR edges
    have none of their own -- and sorting would otherwise lose it.
    """
    position = {node.node_id: index for index, node in enumerate(flow_nodes)}
    last = len(position)
    return sorted(
        enumerate(graph.edges),
        key=lambda pair: (position.get(pair[1].from_id, last), pair[1].order, pair[0]),
    )
