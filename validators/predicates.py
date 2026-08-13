"""The individual checks, as pure generators of findings.

Every flow predicate runs over the *control-flow subgraph* rather than the raw
graph. Annotation nodes are attached by dashed ``annotates`` edges and carry no
sequence flow, so including them would make well-formed graphs look like they
were full of orphans and dead ends. :func:`flow_view` builds that subgraph once
and the predicates share it.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from ir.models import Edge, EdgeType, Node, NodeStatus, NodeType, ProcessGraph
from ir.skeleton import Skeleton
from validators.report import Finding, FindingCode

FLOW_EDGE_TYPES = frozenset({EdgeType.PRECEDES, EdgeType.BRANCH})


@dataclass(frozen=True)
class FlowView:
    """The control-flow subgraph: no annotation nodes, no ``annotates`` edges."""

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    outgoing: Mapping[str, tuple[Edge, ...]]
    incoming: Mapping[str, tuple[Edge, ...]]

    @property
    def ids(self) -> frozenset[str]:
        """The ids of every node participating in control flow."""
        return frozenset(node.id for node in self.nodes)

    def of_type(self, node_type: NodeType) -> tuple[Node, ...]:
        """Every flow node of the given type."""
        return tuple(node for node in self.nodes if node.type is node_type)


def flow_view(graph: ProcessGraph) -> FlowView:
    """Project a graph onto its control-flow subgraph."""
    nodes = tuple(node for node in graph.nodes if node.type is not NodeType.ANNOTATION)
    flow_ids = {node.id for node in nodes}
    edges = tuple(
        edge
        for edge in graph.edges
        if edge.type in FLOW_EDGE_TYPES and edge.from_id in flow_ids and edge.to_id in flow_ids
    )

    outgoing: defaultdict[str, list[Edge]] = defaultdict(list)
    incoming: defaultdict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.from_id].append(edge)
        incoming[edge.to_id].append(edge)

    return FlowView(
        nodes=nodes,
        edges=edges,
        outgoing={node_id: tuple(items) for node_id, items in outgoing.items()},
        incoming={node_id: tuple(items) for node_id, items in incoming.items()},
    )


def check_unique_node_ids(graph: ProcessGraph) -> Iterator[Finding]:
    """Node ids must be unique, or every edge reference is ambiguous."""
    counts = Counter(node.id for node in graph.nodes)
    for node_id, count in sorted(counts.items()):
        if count > 1:
            yield Finding.of(
                FindingCode.DUPLICATE_NODE_ID,
                f"node id '{node_id}' is used by {count} nodes; ids must be unique",
                node_id,
            )


def check_edge_references(graph: ProcessGraph) -> Iterator[Finding]:
    """Every edge endpoint must name a node that exists."""
    known = {node.id for node in graph.nodes}
    for index, edge in enumerate(graph.edges):
        for side, node_id in (("from_id", edge.from_id), ("to_id", edge.to_id)):
            if node_id not in known:
                yield Finding.of(
                    FindingCode.DANGLING_EDGE_REF,
                    f"edge {index} ({edge.from_id} -> {edge.to_id}) has {side} '{node_id}', which is not a node",
                    node_id,
                )


def check_annotation_wiring(graph: ProcessGraph) -> Iterator[Finding]:
    """Annotations attach to the flow by a dashed edge and never sit inside it.

    This is what licenses every other flow predicate to ignore annotation nodes.
    """
    annotation_ids = {node.id for node in graph.nodes if node.type is NodeType.ANNOTATION}
    described_by: defaultdict[str, int] = defaultdict(int)

    for edge in graph.edges:
        if edge.type is EdgeType.ANNOTATES:
            if edge.from_id not in annotation_ids:
                yield Finding.of(
                    FindingCode.MALFORMED_ANNOTATION,
                    f"annotates edge leaves '{edge.from_id}', which is not an annotation node",
                    edge.from_id,
                )
            else:
                described_by[edge.from_id] += 1
            if edge.to_id in annotation_ids:
                yield Finding.of(
                    FindingCode.MALFORMED_ANNOTATION,
                    f"annotates edge points at '{edge.to_id}', which is itself an annotation node",
                    edge.to_id,
                )
        elif edge.type in FLOW_EDGE_TYPES:
            for node_id in (edge.from_id, edge.to_id):
                if node_id in annotation_ids:
                    yield Finding.of(
                        FindingCode.MALFORMED_ANNOTATION,
                        f"annotation node '{node_id}' is wired into the flow by a {edge.type} edge; "
                        f"annotations attach with an annotates edge instead",
                        node_id,
                    )

    for node_id in sorted(annotation_ids - described_by.keys()):
        yield Finding.of(
            FindingCode.MALFORMED_ANNOTATION,
            f"annotation node '{node_id}' describes nothing; it needs an annotates edge to the box it applies to",
            node_id,
        )


def check_single_start(view: FlowView) -> Iterator[Finding]:
    """Exactly one start node. Multiple intake channels collapse into one entry point."""
    starts = view.of_type(NodeType.START)
    if len(starts) == 1:
        return
    if not starts:
        yield Finding.of(FindingCode.START_NODE_COUNT, "the graph has no start node; exactly one is required")
    else:
        named = ", ".join(f"'{node.id}'" for node in starts)
        yield Finding.of(
            FindingCode.START_NODE_COUNT,
            f"the graph has {len(starts)} start nodes ({named}); collapse them into one",
            *(node.id for node in starts),
        )


def check_gateway_branches(view: FlowView) -> Iterator[Finding]:
    """Every gateway needs at least two branches, each carrying a condition."""
    for gateway in view.of_type(NodeType.GATEWAY):
        branches = tuple(e for e in view.outgoing.get(gateway.id, ()) if e.type is EdgeType.BRANCH)
        if len(branches) < 2:
            yield Finding.of(
                FindingCode.GATEWAY_BRANCHES,
                f"gateway '{gateway.id}' has {len(branches)} branch edge(s); a decision needs at least two",
                gateway.id,
            )
        unguarded = [e for e in branches if e.condition is None or not e.condition.strip()]
        if unguarded:
            targets = ", ".join(f"'{e.to_id}'" for e in unguarded)
            yield Finding.of(
                FindingCode.GATEWAY_BRANCHES,
                f"gateway '{gateway.id}' has branch(es) to {targets} with no condition",
                gateway.id,
            )


def check_no_orphans(view: FlowView) -> Iterator[Finding]:
    """Every non-start node is entered, and every non-terminal node is left."""
    for node in view.nodes:
        if node.type is not NodeType.START and not view.incoming.get(node.id):
            yield Finding.of(
                FindingCode.ORPHAN_NODE,
                f"node '{node.id}' has no incoming flow and is not the start node",
                node.id,
            )
        if node.type is not NodeType.TERMINAL and not view.outgoing.get(node.id):
            yield Finding.of(
                FindingCode.ORPHAN_NODE,
                f"node '{node.id}' has no outgoing flow and is not a terminal",
                node.id,
            )


def check_terminal_reachable(view: FlowView) -> Iterator[Finding]:
    """Every node can still get to an end state.

    Walked backwards from the terminals rather than forwards from the start, so a
    rework loop back to an earlier step does not read as a dead end.
    """
    terminals = view.of_type(NodeType.TERMINAL)
    if not terminals:
        yield Finding.of(FindingCode.TERMINAL_UNREACHABLE, "the graph has no terminal node; no path can end")
        return

    predecessors: defaultdict[str, list[str]] = defaultdict(list)
    for edge in view.edges:
        predecessors[edge.to_id].append(edge.from_id)

    co_reaching = _walk({node.id for node in terminals}, predecessors)
    for node_id in sorted(view.ids - co_reaching):
        yield Finding.of(
            FindingCode.TERMINAL_UNREACHABLE,
            f"no path from node '{node_id}' reaches a terminal",
            node_id,
        )


def check_reachable_from_start(view: FlowView) -> Iterator[Finding]:
    """Every node is reachable from the start.

    Catches a self-contained island that satisfies every local rule -- each node
    entered and left, its own terminal present -- but is not part of the process.
    """
    starts = view.of_type(NodeType.START)
    if not starts:
        return

    successors: defaultdict[str, list[str]] = defaultdict(list)
    for edge in view.edges:
        successors[edge.from_id].append(edge.to_id)

    reachable = _walk({node.id for node in starts}, successors)
    for node_id in sorted(view.ids - reachable):
        yield Finding.of(
            FindingCode.UNREACHABLE_FROM_START,
            f"node '{node_id}' cannot be reached from the start node",
            node_id,
        )


def check_required_subprocesses(graph: ProcessGraph, skeleton: Skeleton) -> Iterator[Finding]:
    """Every subprocess the skeleton expects is accounted for somewhere in the graph."""
    present = {node.subprocess for node in graph.nodes if node.subprocess}
    for spec in skeleton.in_hint_order():
        if spec.name not in present:
            yield Finding.of(
                FindingCode.MISSING_REQUIRED_SUBPROCESS,
                f"the source text does not describe the '{spec.name}' subprocess ({spec.label}); "
                f"a human should confirm whether it is genuinely absent",
            )


def check_known_subprocesses(graph: ProcessGraph, skeleton: Skeleton) -> Iterator[Finding]:
    """Nodes only claim subprocesses the skeleton declares."""
    required = skeleton.required_names
    for node in graph.nodes:
        if node.subprocess and node.subprocess not in required:
            yield Finding.of(
                FindingCode.UNKNOWN_SUBPROCESS,
                f"node '{node.id}' claims subprocess '{node.subprocess}', which the skeleton does not declare",
                node.id,
            )


ACTORLESS_NODE_TYPES = frozenset({NodeType.TERMINAL, NodeType.ANNOTATION})
ATTRIBUTED_NODE_TYPES = frozenset({NodeType.TASK, NodeType.GATEWAY})


def check_actor_placement(graph: ProcessGraph) -> Iterator[Finding]:
    """An actor performs work; an end state and a note are not work.

    Two directions of one rule. Putting an actor on a terminal or an annotation is
    structural: it would give the renderer a lane for something nobody performs.
    Leaving a task or gateway unattributed is a resolution finding instead -- the
    process config may not declare a default lane to fall back to, and an
    unattributed step is a question for a human, not a malformed graph.

    ``start`` and ``subprocess`` nodes are exempt in both directions: an entry point
    need not be performed by anyone, and a collapsed subprocess may span several
    actors.
    """
    for node in graph.nodes:
        if node.type in ACTORLESS_NODE_TYPES and node.actor is not None:
            yield Finding.of(
                FindingCode.MISPLACED_ACTOR,
                f"{node.type} node '{node.id}' carries the actor '{node.actor}'; "
                f"a {node.type} is not work anyone performs",
                node.id,
            )
        elif node.type in ATTRIBUTED_NODE_TYPES and node.actor is None:
            yield Finding.of(
                FindingCode.UNATTRIBUTED_STEP,
                f"{node.type} node '{node.id}' ({node.label}) names nobody; a human should confirm who performs it",
                node.id,
            )


def check_clarification_detail(graph: ProcessGraph) -> Iterator[Finding]:
    """A node a human must resolve has to say what is open.

    Structural rather than resolution: an open question with no statement of what
    is open tells the reviewer nothing, and unlike the ambiguity itself this is a
    mechanical omission the model can fix from its own extraction.
    """
    for node in graph.nodes:
        if node.status is NodeStatus.NEEDS_CLARIFICATION and (node.detail is None or not node.detail.strip()):
            yield Finding.of(
                FindingCode.MISSING_CLARIFICATION_DETAIL,
                f"node '{node.id}' ({node.label}) is marked needs_clarification but its detail does not "
                f"say what the source leaves open",
                node.id,
            )


def check_needs_clarification(graph: ProcessGraph) -> Iterator[Finding]:
    """Enumerate the tagged ambiguities so they surface in the report."""
    for node in graph.nodes:
        if node.status is NodeStatus.NEEDS_CLARIFICATION:
            detail = f": {node.detail}" if node.detail else ""
            yield Finding.of(
                FindingCode.NEEDS_CLARIFICATION,
                f"node '{node.id}' ({node.label}) needs human confirmation{detail}",
                node.id,
            )


def _walk(seeds: set[str], adjacency: Mapping[str, list[str]]) -> set[str]:
    """Depth-first closure of ``seeds`` over ``adjacency``.

    Only the closure is used, so the traversal order is not significant.
    """
    seen = set(seeds)
    queue = list(seeds)
    while queue:
        current = queue.pop()
        for neighbour in adjacency.get(current, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen
