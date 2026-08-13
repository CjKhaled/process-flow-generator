"""Terse constructors for graph fixtures.

Tests need to build deliberately broken graphs, so these wrap the IR models with
defaults rather than adding any validation of their own.
"""

from ir.models import Edge, EdgeType, Node, NodeStatus, NodeType, ProcessGraph
from validators.report import FindingCode, ValidationReport


def node(
    node_id: str,
    node_type: NodeType = NodeType.TASK,
    *,
    label: str | None = None,
    status: NodeStatus = NodeStatus.STATED,
    actor: str | None = None,
    subprocess: str | None = None,
    detail: str | None = None,
    alternatives: tuple[str, ...] = (),
) -> Node:
    """Build a node, defaulting to a plain stated task."""
    return Node(
        id=node_id,
        type=node_type,
        label=label or node_id.replace("_", " ").title(),
        status=status,
        actor=actor,
        subprocess=subprocess,
        detail=detail,
        alternatives=alternatives,
    )


def edge(
    from_id: str,
    to_id: str,
    edge_type: EdgeType = EdgeType.PRECEDES,
    *,
    condition: str | None = None,
    order: int = 0,
) -> Edge:
    """Build an edge, defaulting to plain sequence flow."""
    return Edge(from_id=from_id, to_id=to_id, type=edge_type, condition=condition, order=order)


def branch(from_id: str, to_id: str, condition: str | None, order: int = 0) -> Edge:
    """Build a gateway branch edge."""
    return edge(from_id, to_id, EdgeType.BRANCH, condition=condition, order=order)


def graph(nodes: tuple[Node, ...], edges: tuple[Edge, ...], name: str = "enrollment") -> ProcessGraph:
    """Build a process graph from nodes and edges."""
    return ProcessGraph(process_name=name, nodes=nodes, edges=edges)


def codes(report: ValidationReport) -> frozenset[FindingCode]:
    """The distinct finding codes in a report, for terse assertions."""
    return frozenset(finding.code for finding in report.findings)
