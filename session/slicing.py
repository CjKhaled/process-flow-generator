"""Cut a subprocess out of the master graph as a flow of its own.

A session keeps **one** graph. A subprocess is a tag on some of its nodes, not a
second graph, so the main flow and a subprocess flow can never disagree about a
step: there is only one copy of it. Whenever a subprocess has to be shown or
drawn by itself, it is sliced out here, by code, from that one graph.

A slice is the tagged nodes and the edges among them, made into a complete
process by adding what the cut removed:

* **One start**, labelled with what hands work into the subprocess
  (``process.yaml``'s ``entry``), wired to every node that was entered from
  outside.
* **A terminal for every way out.** An edge leaving the subprocess becomes an
  edge to an end state saying where the work goes: "Return to main flow: <the
  step it returns to>", or the outside terminal's own label when the path ends
  the process there.

Both kinds are marked ``origin: slice`` so nothing downstream mistakes them for
something the user said. Every other node is the master graph's node, unchanged
except that its subprocess tag is cleared -- within its own flow it is simply a
step, and leaving the tag would have stage 2 look for a box to fold it into.

A slice is a valid graph by construction, and :func:`slice_subprocess` checks it:
a slice that fails the structural tier is a bug here, not a property of what the
user said.
"""

from ir.models import Edge, EdgeType, Node, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from ir.skeleton import Skeleton
from knowledge.schemas import ProcessFile, SubprocessDef
from session.models import Session
from validators.graph import validate

START_ID = "slice_start"
EXIT_PREFIX = "slice_exit_"
RETURN_PREFIX = "Return to main flow: "

EMPTY_SKELETON = Skeleton(subprocesses=())
"""A subprocess flow hands nothing off, so it has no boxes of its own to collapse."""


class SliceError(RuntimeError):
    """A slice came out structurally invalid. A defect in the slicer, never in the input."""


def flow_name(process: ProcessFile, subprocess_id: str | None = None) -> str:
    """The machine name of a flow: the process, or the process and one of its subprocesses."""
    return process.id if subprocess_id is None else f"{process.id}_{subprocess_id}"


def members(graph: ProcessGraph, subprocess_id: str) -> tuple[Node, ...]:
    """The flow nodes tagged with a subprocess, in graph order.

    A start node is never a member, whatever its tag: a process has one way in,
    and it belongs to the main flow.
    """
    return tuple(
        node
        for node in graph.nodes
        if node.subprocess == subprocess_id and node.type not in (NodeType.START, NodeType.ANNOTATION)
    )


def handoff_lane(session: Session, process: ProcessFile, sub: SubprocessDef) -> str:
    """The lane a subprocess's collapsed box is drawn in.

    The lane of whoever hands the work off -- the step outside the subprocess
    that leads into it, which is the deciding gateway. Where the flow has no
    such step yet, the session's lane for the subprocess's usual persona; where
    there is none of those either, the default lane.
    """
    inside = {node.id for node in members(session.graph, sub.id)}
    by_id = {node.id: node for node in session.graph.nodes}
    for edge in session.graph.edges:
        source = by_id.get(edge.from_id)
        crosses_in = edge.type is not EdgeType.ANNOTATES and edge.to_id in inside and edge.from_id not in inside
        if crosses_in and source is not None and source.actor:
            return source.actor
    learned = next((lane.name for lane in session.lanes if lane.persona == sub.persona), None)
    return learned or session.default_lane


def slice_subprocess(graph: ProcessGraph, sub: SubprocessDef, process: ProcessFile) -> ProcessGraph | None:
    """Cut one subprocess out of the master graph.

    Args:
        graph: The master graph. Never modified.
        sub: The subprocess to cut out.
        process: The process definition, for the flow's name.

    Returns:
        The subprocess as a complete graph, or None if no step is tagged with it.

    Raises:
        SliceError: If the result fails the structural tier.
    """
    inside_nodes = members(graph, sub.id)
    if not inside_nodes:
        return None
    inside = {node.id for node in inside_nodes}
    by_id = {node.id: node for node in graph.nodes}

    entries: list[str] = []
    exits: dict[str, Node] = {}
    edges: list[Edge] = []
    for edge in graph.edges:
        if edge.type is EdgeType.ANNOTATES:
            continue
        leaves, enters = edge.from_id in inside, edge.to_id in inside
        if leaves and enters:
            edges.append(edge)
        elif enters and edge.to_id not in entries:
            entries.append(edge.to_id)
        elif leaves and edge.to_id in by_id:
            target = by_id[edge.to_id]
            exits.setdefault(target.id, _exit(target))
            edges.append(edge.model_copy(update={"to_id": exits[target.id].id}))

    # A subprocess nothing leads into yet is entered at its first step, in graph order.
    order = {node.id: index for index, node in enumerate(inside_nodes)}
    entries = sorted(entries, key=order.__getitem__) or [inside_nodes[0].id]

    start = Node(
        id=START_ID,
        type=NodeType.START,
        label=sub.entry,
        actor=by_id[entries[0]].actor,
        status=NodeStatus.STATED,
        origin=NodeOrigin.SLICE,
    )
    notes = [
        (node, edge)
        for edge in graph.edges
        if edge.type is EdgeType.ANNOTATES and edge.to_id in inside and (node := by_id.get(edge.from_id)) is not None
    ]
    sliced = ProcessGraph(
        process_name=flow_name(process, sub.id),
        nodes=(
            start,
            *(_untagged(node) for node in inside_nodes),
            *(_untagged(node) for node, _ in notes),
            *exits.values(),
        ),
        edges=(
            *(
                Edge(from_id=START_ID, to_id=entry, type=EdgeType.PRECEDES, order=index)
                for index, entry in enumerate(entries)
            ),
            *edges,
            *(edge for _, edge in notes),
        ),
    )

    report = validate(sliced, EMPTY_SKELETON)
    if not report.is_structurally_valid:
        raise SliceError(f"the '{sub.id}' slice is not structurally valid:\n{report.summary()}")
    return sliced


def _untagged(node: Node) -> Node:
    return node.model_copy(update={"subprocess": None})


def _exit(target: Node) -> Node:
    """The end state standing for one way out of the subprocess.

    Where the path runs into an outside terminal, the process ends there and the
    exit says what that terminal says -- open question included, since a reader
    of this flow needs to know the outcome is unsettled. Otherwise the work goes
    back to the main flow, and the exit names the step that picks it up.

    Its lane is the target's: the lane that owns the outcome, by the same rule
    every terminal follows.
    """
    ends_process = target.type is NodeType.TERMINAL
    return Node(
        id=f"{EXIT_PREFIX}{target.id}",
        type=NodeType.TERMINAL,
        label=target.label if ends_process else f"{RETURN_PREFIX}{target.label}",
        actor=target.actor,
        status=target.status if ends_process else NodeStatus.STATED,
        detail=target.detail if ends_process else None,
        origin=NodeOrigin.SLICE,
    )
