"""Validator predicate tests.

Each test builds a graph exhibiting exactly one defect and asserts the validator
reacts to it. The structural tier must be a hard gate; the resolution tier must
tag and pass through.
"""

import pytest

from ir.models import EdgeType, NodeStatus, NodeType, ProcessGraph
from ir.skeleton import Skeleton
from tests.builders import branch, codes, edge, graph, node
from validators.graph import validate
from validators.report import FindingCode, Severity


def test_valid_graph_passes_the_structural_tier(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """A sound graph produces no structural findings."""
    report = validate(valid_graph, enrollment_skeleton)

    assert report.is_structurally_valid
    assert report.structural == ()


def test_dangling_gateway_is_reported(enrollment_skeleton: Skeleton) -> None:
    """A gateway with a single outgoing branch fails the structural tier."""
    broken = graph(
        nodes=(
            node("start", NodeType.START),
            node("gw", NodeType.GATEWAY),
            node("end", NodeType.TERMINAL),
        ),
        edges=(
            edge("start", "gw"),
            branch("gw", "end", "prescriber agrees"),
        ),
    )

    report = validate(broken, enrollment_skeleton)

    assert not report.is_structurally_valid
    assert FindingCode.GATEWAY_BRANCHES in codes(report)


def test_branch_without_a_condition_is_reported(enrollment_skeleton: Skeleton) -> None:
    """Two branches are not enough; each one needs a guard."""
    broken = graph(
        nodes=(
            node("start", NodeType.START),
            node("gw", NodeType.GATEWAY),
            node("end_a", NodeType.TERMINAL),
            node("end_b", NodeType.TERMINAL),
        ),
        edges=(
            edge("start", "gw"),
            branch("gw", "end_a", "prescriber agrees", order=0),
            branch("gw", "end_b", None, order=1),
        ),
    )

    report = validate(broken, enrollment_skeleton)

    assert not report.is_structurally_valid
    assert FindingCode.GATEWAY_BRANCHES in codes(report)


def test_broken_edge_reference_is_reported(enrollment_skeleton: Skeleton) -> None:
    """An edge pointing at a node that does not exist fails the structural tier."""
    broken = graph(
        nodes=(node("start", NodeType.START), node("end", NodeType.TERMINAL)),
        edges=(edge("start", "does_not_exist"),),
    )

    report = validate(broken, enrollment_skeleton)

    assert not report.is_structurally_valid
    assert FindingCode.DANGLING_EDGE_REF in codes(report)
    assert any("does_not_exist" in finding.message for finding in report.structural)


def test_missing_required_subprocess_is_a_resolution_finding(
    valid_graph: ProcessGraph, enrollment_skeleton: Skeleton
) -> None:
    """The absent missing_info subprocess is tagged, not dropped, and does not block emission."""
    report = validate(valid_graph, enrollment_skeleton)
    missing = [f for f in report.resolution if f.code is FindingCode.MISSING_REQUIRED_SUBPROCESS]

    assert report.is_structurally_valid
    assert len(missing) == 1
    assert "missing_info" in missing[0].message
    assert missing[0].severity is Severity.RESOLUTION


def test_duplicate_node_ids_are_reported(enrollment_skeleton: Skeleton) -> None:
    """Node ids must be unique or every edge reference is ambiguous."""
    broken = graph(
        nodes=(node("start", NodeType.START), node("start", NodeType.TERMINAL)),
        edges=(),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.DUPLICATE_NODE_ID in codes(report)


def test_multiple_starts_are_reported(enrollment_skeleton: Skeleton) -> None:
    """Intake channels collapse into one start; two start nodes is a defect."""
    broken = graph(
        nodes=(
            node("start_portal", NodeType.START),
            node("start_fax", NodeType.START),
            node("end", NodeType.TERMINAL),
        ),
        edges=(edge("start_portal", "end"), edge("start_fax", "end")),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.START_NODE_COUNT in codes(report)


def test_dead_end_is_reported(enrollment_skeleton: Skeleton) -> None:
    """A non-terminal node with no outgoing flow never reaches an end state."""
    broken = graph(
        nodes=(node("start", NodeType.START), node("stuck"), node("end", NodeType.TERMINAL)),
        edges=(edge("start", "stuck"), edge("start", "end", order=1)),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.ORPHAN_NODE in codes(report)
    assert FindingCode.TERMINAL_UNREACHABLE in codes(report)


def test_island_unreachable_from_start_is_reported(enrollment_skeleton: Skeleton) -> None:
    """A self-contained island passes every local check yet is still unreachable.

    Each island node has an incoming and an outgoing edge, and the island has its
    own terminal, so the orphan and terminal-reachability rules are both satisfied.
    Only a forward walk from the start node catches it.
    """
    broken = graph(
        nodes=(
            node("start", NodeType.START),
            node("end", NodeType.TERMINAL),
            node("island_a"),
            node("island_b"),
            node("island_end", NodeType.TERMINAL),
        ),
        edges=(
            edge("start", "end"),
            edge("island_a", "island_b"),
            edge("island_b", "island_a", order=1),
            edge("island_b", "island_end", order=2),
        ),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.UNREACHABLE_FROM_START in codes(report)
    assert FindingCode.ORPHAN_NODE not in codes(report)


def test_annotation_node_is_not_an_orphan(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """Annotations hang off the flow by a dashed edge and must be excluded from flow checks."""
    report = validate(valid_graph, enrollment_skeleton)

    assert FindingCode.ORPHAN_NODE not in codes(report)
    assert FindingCode.TERMINAL_UNREACHABLE not in codes(report)
    assert FindingCode.UNREACHABLE_FROM_START not in codes(report)


def test_annotation_in_the_flow_is_reported(enrollment_skeleton: Skeleton) -> None:
    """An annotation wired with sequence flow would corrupt every flow predicate."""
    broken = graph(
        nodes=(
            node("start", NodeType.START),
            node("ann", NodeType.ANNOTATION),
            node("end", NodeType.TERMINAL),
        ),
        edges=(edge("start", "ann"), edge("ann", "end")),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.MALFORMED_ANNOTATION in codes(report)


def test_annotates_edge_must_leave_an_annotation(enrollment_skeleton: Skeleton) -> None:
    """A dashed edge runs annotation -> described box, never the other way round."""
    broken = graph(
        nodes=(
            node("start", NodeType.START),
            node("end", NodeType.TERMINAL),
            node("ann", NodeType.ANNOTATION),
        ),
        edges=(edge("start", "end"), edge("end", "ann", EdgeType.ANNOTATES)),
    )

    report = validate(broken, enrollment_skeleton)

    assert FindingCode.MALFORMED_ANNOTATION in codes(report)


def test_rework_loop_still_reaches_a_terminal(enrollment_skeleton: Skeleton) -> None:
    """A cycle back to an earlier step is normal in these processes and must not read as a dead end."""
    looping = graph(
        nodes=(
            node("start", NodeType.START),
            node("review"),
            node("gw_complete", NodeType.GATEWAY),
            node("end", NodeType.TERMINAL),
        ),
        edges=(
            edge("start", "review"),
            edge("review", "gw_complete"),
            branch("gw_complete", "end", "information is complete", order=0),
            branch("gw_complete", "review", "information is missing", order=1),
        ),
    )

    report = validate(looping, enrollment_skeleton)

    assert report.is_structurally_valid


def test_subprocess_order_is_not_enforced(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """order_hint is a layout hint; the real text runs off_label before duplicate."""
    hints = {spec.name: spec.order_hint for spec in enrollment_skeleton.subprocesses}
    report = validate(valid_graph, enrollment_skeleton)

    assert hints["off_label"] < hints["duplicate"]
    assert report.is_structurally_valid
    assert all("order" not in finding.message for finding in report.findings)


def test_unknown_subprocess_is_a_resolution_finding(enrollment_skeleton: Skeleton) -> None:
    """A subprocess name outside the skeleton is tagged but does not block emission."""
    graph_with_unknown = graph(
        nodes=(
            node("start", NodeType.START, subprocess="intake"),
            node("end", NodeType.TERMINAL, subprocess="prior_authorization"),
        ),
        edges=(edge("start", "end"),),
    )

    report = validate(graph_with_unknown, enrollment_skeleton)

    assert report.is_structurally_valid
    assert FindingCode.UNKNOWN_SUBPROCESS in codes(report)
    assert any("prior_authorization" in f.message for f in report.resolution)


def test_needs_clarification_nodes_are_enumerated(enrollment_skeleton: Skeleton) -> None:
    """Unstated branches pass through tagged, and the report names them."""
    tagged = graph(
        nodes=(
            node("start", NodeType.START),
            node("gw_agrees", NodeType.GATEWAY),
            node("end_enrolled", NodeType.TERMINAL),
            node(
                "end_unknown",
                NodeType.TERMINAL,
                status=NodeStatus.NEEDS_CLARIFICATION,
                detail="the source does not say what happens when the prescriber disagrees",
            ),
        ),
        edges=(
            edge("start", "gw_agrees"),
            branch("gw_agrees", "end_enrolled", "prescriber agrees", order=0),
            branch("gw_agrees", "end_unknown", "prescriber does not agree", order=1),
        ),
    )

    report = validate(tagged, enrollment_skeleton)
    clarifications = [f for f in report.resolution if f.code is FindingCode.NEEDS_CLARIFICATION]

    assert report.is_structurally_valid
    assert len(clarifications) == 1
    assert clarifications[0].node_ids == ("end_unknown",)


@pytest.mark.parametrize("node_type", [NodeType.TERMINAL, NodeType.ANNOTATION])
def test_an_actor_on_a_non_work_node_is_structural(enrollment_skeleton: Skeleton, node_type: NodeType) -> None:
    """A lane for something nobody performs would mislead the renderer."""
    misplaced = graph(
        nodes=(
            node("start", NodeType.START),
            node("do_it", actor="CM360"),
            node("tail", node_type, actor="CM360"),
        ),
        edges=(
            edge("start", "do_it"),
            edge("do_it", "tail") if node_type is NodeType.TERMINAL else edge("tail", "do_it", EdgeType.ANNOTATES),
        ),
    )

    report = validate(misplaced, enrollment_skeleton)

    assert not report.is_structurally_valid
    assert FindingCode.MISPLACED_ACTOR in codes(report)


def test_an_unattributed_step_is_only_a_resolution_finding(enrollment_skeleton: Skeleton) -> None:
    """Who performs a step is a question for a human, not a malformed graph."""
    unattributed = graph(
        nodes=(node("start", NodeType.START), node("do_it"), node("end", NodeType.TERMINAL)),
        edges=(edge("start", "do_it"), edge("do_it", "end")),
    )

    report = validate(unattributed, enrollment_skeleton)

    assert report.is_structurally_valid
    assert FindingCode.UNATTRIBUTED_STEP in codes(report)
    assert any("do_it" in f.message for f in report.resolution)


def test_an_attributed_graph_raises_no_actor_findings(enrollment_skeleton: Skeleton) -> None:
    """Work named, outcomes left blank: neither direction of the rule fires."""
    attributed = graph(
        nodes=(
            node("start", NodeType.START, actor="HCP"),
            node("gw", NodeType.GATEWAY, actor="CM360"),
            node("do_it", actor="JCRM"),
            node("end", NodeType.TERMINAL),
        ),
        edges=(
            edge("start", "gw"),
            branch("gw", "do_it", "patient is new", order=0),
            branch("gw", "end", "patient already exists", order=1),
            edge("do_it", "end"),
        ),
    )

    report = validate(attributed, enrollment_skeleton)

    assert report.is_structurally_valid
    assert FindingCode.MISPLACED_ACTOR not in codes(report)
    assert FindingCode.UNATTRIBUTED_STEP not in codes(report)


@pytest.mark.parametrize("detail", [None, "   "])
def test_clarification_without_detail_is_structural(enrollment_skeleton: Skeleton, detail: str | None) -> None:
    """An open question that does not say what is open is a mechanical omission."""
    undetailed = graph(
        nodes=(
            node("start", NodeType.START),
            node("end_unknown", NodeType.TERMINAL, status=NodeStatus.NEEDS_CLARIFICATION, detail=detail),
        ),
        edges=(edge("start", "end_unknown"),),
    )

    report = validate(undetailed, enrollment_skeleton)

    assert not report.is_structurally_valid
    assert FindingCode.MISSING_CLARIFICATION_DETAIL in codes(report)
    assert all(f.code is not FindingCode.MISSING_CLARIFICATION_DETAIL for f in report.resolution)


def test_clarification_with_detail_is_only_a_resolution_finding(enrollment_skeleton: Skeleton) -> None:
    """A justified open question passes the hard tier and is reported for a human."""
    detailed = graph(
        nodes=(
            node("start", NodeType.START),
            node(
                "end_unknown",
                NodeType.TERMINAL,
                status=NodeStatus.NEEDS_CLARIFICATION,
                detail="the source stops before saying how this ends",
            ),
        ),
        edges=(edge("start", "end_unknown"),),
    )

    report = validate(detailed, enrollment_skeleton)

    assert report.is_structurally_valid
    assert FindingCode.MISSING_CLARIFICATION_DETAIL not in codes(report)
    assert FindingCode.NEEDS_CLARIFICATION in codes(report)


def test_stated_nodes_need_no_detail(enrollment_skeleton: Skeleton) -> None:
    """The detail requirement is scoped to open questions, not to every node."""
    plain = graph(
        nodes=(node("start", NodeType.START), node("end", NodeType.TERMINAL)),
        edges=(edge("start", "end"),),
    )

    report = validate(plain, enrollment_skeleton)

    assert report.is_structurally_valid
    assert FindingCode.MISSING_CLARIFICATION_DETAIL not in codes(report)


def test_report_separates_the_two_tiers(enrollment_skeleton: Skeleton) -> None:
    """Structural and resolution findings are addressable independently."""
    broken = graph(
        nodes=(node("start", NodeType.START),),
        edges=(edge("start", "missing"),),
    )

    report = validate(broken, enrollment_skeleton)

    assert all(f.severity is Severity.STRUCTURAL for f in report.structural)
    assert all(f.severity is Severity.RESOLUTION for f in report.resolution)
    assert len(report.findings) == len(report.structural) + len(report.resolution)


def test_dangling_reference_short_circuits_flow_checks(enrollment_skeleton: Skeleton) -> None:
    """With a broken reference the flow predicates cannot be trusted, so they are not run."""
    broken = graph(
        nodes=(node("start", NodeType.START), node("end", NodeType.TERMINAL)),
        edges=(edge("start", "typo"),),
    )

    report = validate(broken, enrollment_skeleton)
    structural_codes = {finding.code for finding in report.structural}

    assert structural_codes == {FindingCode.DANGLING_EDGE_REF}
