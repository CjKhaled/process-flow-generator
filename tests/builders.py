"""Terse constructors for graph fixtures.

Tests need to build deliberately broken graphs, so these wrap the IR models with
defaults rather than adding any validation of their own.
"""

from ir.models import Edge, EdgeType, Node, NodeStatus, NodeType, ProcessGraph
from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton, SubprocessSpec
from validators.report import FindingCode, ValidationReport


def node(
    node_id: str,
    node_type: NodeType = NodeType.TASK,
    *,
    label: str | None = None,
    status: NodeStatus = NodeStatus.STATED,
    # Every box sits in a swimlane, so the default has to be a real one or every
    # fixture would trip check_swimlane. Pass actor=None to build that defect.
    actor: str | None = "CM360",
    subprocess: str | None = None,
    detail: str | None = None,
    alternatives: tuple[str, ...] = (),
) -> Node:
    """Build a node, defaulting to a plain stated task in the CM360 lane."""
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


def config(
    actors: tuple[str, ...] = ("CM360",),
    *,
    name: str = "enrollment",
    display_name: str = "Intake & Enrollment",
) -> ProcessConfig:
    """Build a process config, with descriptions the tests never read."""
    return ProcessConfig(
        process_name=name,
        display_name=display_name,
        actors={actor: f"the {actor}" for actor in actors},
        default_actor=actors[0] if actors else None,
    )


def skeleton(*names: str, name: str = "enrollment") -> Skeleton:
    """Build a skeleton whose subprocesses are in the order given."""
    return Skeleton(
        process_name=name,
        subprocesses=tuple(
            SubprocessSpec(name=item, label=item.replace("_", " ").title(), order_hint=position)
            for position, item in enumerate(names)
        ),
    )


def codes(report: ValidationReport) -> frozenset[FindingCode]:
    """The distinct finding codes in a report, for terse assertions."""
    return frozenset(finding.code for finding in report.findings)
