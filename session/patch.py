"""Graph patches: what the extractor returns, and how one is applied.

After the first turn the extractor never re-emits the graph. It returns a list
of operations against the graph the session already holds, for two reasons:

* **Ids stay stable.** Coverage topics, pending questions and the rationale a
  reader has open are all keyed by node id. A re-extraction would be free to
  rename every node on every turn.
* **An answer changes little.** Asking for the whole graph again would invite the
  model to revise things nobody mentioned.

The first turn is a patch like any other, against an empty graph, so there is one
path rather than two.

:func:`apply_patch` is pure and **never raises on a bad operation**. An operation
that cannot be applied -- it updates a node that is not there, or adds one that
is -- is skipped and reported as a structural finding, which is what earns the
model a repair turn naming the mistake. Raising would lose the rest of the patch
and tell the model nothing.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ir.models import BranchAnswer, Edge, EdgeType, EvidenceRef, Node, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from validators.report import Finding, FindingCode


class _Op(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NodeFields(_Op):
    """The fields of a node to change. Anything left null stays as it is."""

    type: NodeType | None = Field(default=None, description="New node type, or null to leave it.")
    label: str | None = Field(default=None, min_length=1, description="New label, or null to leave it.")
    actor: str | None = Field(default=None, description="New swimlane, or null to leave it.")
    subprocess: str | None = Field(
        default=None,
        description="New subprocess tag, or null to leave it. To remove the tag, name 'subprocess' in `clear`.",
    )
    status: NodeStatus | None = Field(default=None, description="New status, or null to leave it.")
    detail: str | None = Field(
        default=None,
        description="New detail, or null to leave it. To empty it, name 'detail' in `clear`.",
    )
    alternatives: tuple[str, ...] | None = Field(
        default=None,
        description="The full new list of alternatives, replacing the old one; null to leave it; [] to empty it.",
    )
    evidence: tuple[EvidenceRef, ...] | None = Field(
        default=None,
        description=(
            "The full new evidence list, replacing the old one; null to leave it. When a new "
            "statement adds support to a node, repeat the references it already had and add the "
            "new one."
        ),
    )
    origin: NodeOrigin | None = Field(
        default=None,
        description=(
            "New origin, or null to leave it. Set 'source' when an answer has now stated an "
            "outcome that a 'rule' terminal was standing in for."
        ),
    )
    clear: tuple[Literal["subprocess", "detail"], ...] = Field(
        default=(),
        description="Fields to reset to null. Needed because null above means 'unchanged'.",
    )


class EdgeFields(_Op):
    """The fields of an edge to change. Anything left null stays as it is."""

    to_id: str | None = Field(
        default=None,
        min_length=1,
        description="Re-point the edge at a different node, or null to leave it.",
    )
    type: EdgeType | None = Field(default=None, description="New edge type, or null to leave it.")
    condition: str | None = Field(
        default=None,
        description="New condition, or null to leave it. To remove it, name 'condition' in `clear`.",
    )
    answer: BranchAnswer | None = Field(
        default=None,
        description="New yes/no answer, or null to leave it. To remove it, name 'answer' in `clear`.",
    )
    order: int | None = Field(default=None, ge=0, description="New order, or null to leave it.")
    evidence: tuple[EvidenceRef, ...] | None = Field(
        default=None,
        description="The full new evidence list, replacing the old one; null to leave it.",
    )
    clear: tuple[Literal["condition", "answer"], ...] = Field(
        default=(),
        description="Fields to reset to null. Needed because null above means 'unchanged'.",
    )


class AddNode(_Op):
    """Add a node that is not in the graph yet."""

    op: Literal["add_node"]
    node: Node = Field(description="The whole new node. Its id must not be in use.")


class UpdateNode(_Op):
    """Change some fields of a node already in the graph. Its id never changes."""

    op: Literal["update_node"]
    id: str = Field(min_length=1, description="The id of the node to change, exactly as it appears in the graph.")
    fields: NodeFields = Field(description="Only the fields that change.")


class RemoveNode(_Op):
    """Remove a node. Every edge touching it is removed with it."""

    op: Literal["remove_node"]
    id: str = Field(min_length=1, description="The id of the node to remove.")
    reason_statement_ids: tuple[str, ...] = Field(
        min_length=1,
        description=(
            "The statements that justify the removal: the correction in which the user said "
            "this does not happen, or the answer that replaced it. A node is never removed "
            "without one."
        ),
    )


class AddEdge(_Op):
    """Add an edge between two nodes."""

    op: Literal["add_edge"]
    edge: Edge = Field(description="The whole new edge. Both ends must exist once the patch is applied.")


class UpdateEdge(_Op):
    """Change some fields of an edge already in the graph."""

    op: Literal["update_edge"]
    from_id: str = Field(min_length=1, description="The edge's current from_id.")
    to_id: str = Field(min_length=1, description="The edge's current to_id.")
    order: int = Field(ge=0, description="The edge's current order.")
    fields: EdgeFields = Field(description="Only the fields that change.")


class RemoveEdge(_Op):
    """Remove one edge, leaving both of its nodes."""

    op: Literal["remove_edge"]
    from_id: str = Field(min_length=1, description="The edge's from_id.")
    to_id: str = Field(min_length=1, description="The edge's to_id.")
    order: int = Field(ge=0, description="The edge's order.")
    reason_statement_ids: tuple[str, ...] = Field(
        min_length=1,
        description="The statements that justify the removal, as for a node.",
    )


Operation = Annotated[
    AddNode | UpdateNode | RemoveNode | AddEdge | UpdateEdge | RemoveEdge,
    Field(discriminator="op"),
]


class GraphPatch(BaseModel):
    """The changes the new statements make to the process graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operations: tuple[Operation, ...] = Field(
        description=(
            "Applied in the order given. Only what the new statements change: an empty list is "
            "the right answer when they change nothing in the flow."
        )
    )


def empty_graph(process_name: str) -> ProcessGraph:
    """The graph a session starts from, before anything has been said."""
    return ProcessGraph(process_name=process_name, nodes=(), edges=())


def apply_patch(graph: ProcessGraph, patch: GraphPatch) -> tuple[ProcessGraph, tuple[Finding, ...]]:
    """Apply a patch to a graph.

    Args:
        graph: The graph to change. Never modified; a new one is returned.
        patch: The operations, applied in order.

    Returns:
        The resulting graph, and a structural finding for every operation that
        could not be applied. Such an operation is skipped and the rest still
        run, so the findings describe everything wrong with the patch at once.
    """
    nodes = list(graph.nodes)
    edges = list(graph.edges)
    findings: list[Finding] = []
    added: list[str] = []

    for operation in patch.operations:
        match operation:
            case AddNode(node=node):
                if any(existing.id == node.id for existing in nodes):
                    findings.append(
                        Finding.of(
                            FindingCode.PATCH_DUPLICATE_NODE,
                            f"add_node '{node.id}': a node with that id already exists; use update_node to "
                            f"change it, or choose a new id",
                            node.id,
                        )
                    )
                    continue
                nodes.append(node)
                added.append(node.id)
            case UpdateNode(id=node_id, fields=fields):
                index = _node_index(nodes, node_id)
                if index is None:
                    findings.append(_unknown_node("update_node", node_id))
                    continue
                nodes[index] = _changed_node(nodes[index], fields)
            case RemoveNode(id=node_id):
                index = _node_index(nodes, node_id)
                if index is None:
                    findings.append(_unknown_node("remove_node", node_id))
                    continue
                del nodes[index]
                edges = [edge for edge in edges if node_id not in (edge.from_id, edge.to_id)]
            case AddEdge(edge=edge):
                edges.append(edge)
            case UpdateEdge(from_id=from_id, to_id=to_id, order=order, fields=edge_fields):
                index = _edge_index(edges, from_id, to_id, order)
                if index is None:
                    findings.append(_unknown_edge("update_edge", from_id, to_id, order))
                    continue
                edges[index] = _changed_edge(edges[index], edge_fields)
            case RemoveEdge(from_id=from_id, to_id=to_id, order=order):
                index = _edge_index(edges, from_id, to_id, order)
                if index is None:
                    findings.append(_unknown_edge("remove_edge", from_id, to_id, order))
                    continue
                del edges[index]

    if graph.nodes:
        nodes = _in_narrative_order(nodes, edges, frozenset(added))
    return graph.model_copy(update={"nodes": tuple(nodes), "edges": tuple(edges)}), tuple(findings)


def _node_index(nodes: list[Node], node_id: str) -> int | None:
    return next((index for index, node in enumerate(nodes) if node.id == node_id), None)


def _edge_index(edges: list[Edge], from_id: str, to_id: str, order: int) -> int | None:
    """Find the edge an operation means.

    Edges have no id, so they are named by their ends and their order. The order
    is the part a model gets wrong, so where exactly one edge joins the two nodes
    that edge is taken to be the one meant, whatever order was given.
    """
    between = [index for index, edge in enumerate(edges) if edge.from_id == from_id and edge.to_id == to_id]
    exact = [index for index in between if edges[index].order == order]
    if exact:
        return exact[0]
    return between[0] if len(between) == 1 else None


def _changed_node(node: Node, fields: NodeFields) -> Node:
    update = {
        name: value
        for name in ("type", "label", "actor", "subprocess", "status", "detail", "alternatives", "evidence", "origin")
        if (value := getattr(fields, name)) is not None
    }
    update.update(dict.fromkeys(fields.clear))
    return node.model_copy(update=update)


def _changed_edge(edge: Edge, fields: EdgeFields) -> Edge:
    update = {
        name: value
        for name in ("to_id", "type", "condition", "answer", "order", "evidence")
        if (value := getattr(fields, name)) is not None
    }
    update.update(dict.fromkeys(fields.clear))
    return edge.model_copy(update=update)


def _unknown_node(operation: str, node_id: str) -> Finding:
    return Finding.of(
        FindingCode.PATCH_UNKNOWN_NODE,
        f"{operation} '{node_id}': there is no node with that id in the graph",
        node_id,
    )


def _unknown_edge(operation: str, from_id: str, to_id: str, order: int) -> Finding:
    return Finding.of(
        FindingCode.PATCH_UNKNOWN_EDGE,
        f"{operation} {from_id} -> {to_id} (order {order}): there is no such edge in the graph",
        from_id,
        to_id,
    )


def _in_narrative_order(nodes: list[Node], edges: list[Edge], added: frozenset[str]) -> list[Node]:
    """Move each node a patch added to just after the step that leads to it.

    Node order is the narrative order, and stage 2 lays the diagram out by it. A
    patch can only append, so without this every step learned from an answer
    would sit at the end of the graph however early in the process it happens.
    Existing nodes never move; a new node with nothing leading to it stays where
    it was appended.
    """
    if not added:
        return nodes

    ordered = [node for node in nodes if node.id not in added]
    for node in (node for node in nodes if node.id in added):
        # An annotation follows the box it describes; anything else, whatever flows into it.
        anchors = {edge.to_id if edge.from_id == node.id else edge.from_id for edge in edges if _anchors(edge, node)}
        positions = [index for index, placed in enumerate(ordered) if placed.id in anchors]
        if not positions:
            ordered.append(node)
            continue
        position = max(positions) + 1
        # Past anything this patch already put here, so siblings keep the order they were emitted in.
        while position < len(ordered) and ordered[position].id in added:
            position += 1
        ordered.insert(position, node)
    return ordered


def _anchors(edge: Edge, node: Node) -> bool:
    """Whether this edge says where ``node`` belongs in the narrative."""
    if node.type is NodeType.ANNOTATION:
        return edge.type is EdgeType.ANNOTATES and edge.from_id == node.id
    return edge.type is not EdgeType.ANNOTATES and edge.to_id == node.id and edge.from_id != node.id
