"""The born-valid gate.

Deterministic, no LLM. Composes the predicates in :mod:`validators.predicates`
into a single report over two tiers:

* **structural** -- hard. The graph is malformed and must not be emitted.
* **resolution** -- soft. The graph is well formed but a human must resolve
  something. Tagged and passed through; never a reason to retry extraction.

``validate`` is a pure function: it returns findings and never touches the graph.
"""

from ir.models import ProcessGraph
from ir.skeleton import Skeleton
from validators.predicates import (
    check_annotation_wiring,
    check_edge_references,
    check_gateway_branches,
    check_known_subprocesses,
    check_needs_clarification,
    check_no_orphans,
    check_reachable_from_start,
    check_required_subprocesses,
    check_single_start,
    check_terminal_reachable,
    check_unique_node_ids,
    flow_view,
)
from validators.report import Finding, FindingCode, ValidationReport

_INTEGRITY_CODES = frozenset({FindingCode.DUPLICATE_NODE_ID, FindingCode.DANGLING_EDGE_REF})


def validate(graph: ProcessGraph, skeleton: Skeleton) -> ValidationReport:
    """Check a graph against the structural and resolution tiers.

    Args:
        graph: The extracted graph to check. Never modified.
        skeleton: The subprocesses this process is expected to contain.

    Returns:
        A report holding every finding. Callers gate on
        :attr:`~validators.report.ValidationReport.is_structurally_valid`.
    """
    findings: list[Finding] = []
    findings.extend(check_unique_node_ids(graph))
    findings.extend(check_edge_references(graph))

    # The flow predicates index nodes by id and follow edges between them, so they
    # are only meaningful once ids are unique and every reference resolves.
    # Running them on a graph that fails either check produces noise, not signal.
    if not any(finding.code in _INTEGRITY_CODES for finding in findings):
        findings.extend(check_annotation_wiring(graph))
        view = flow_view(graph)
        findings.extend(check_single_start(view))
        findings.extend(check_gateway_branches(view))
        findings.extend(check_no_orphans(view))
        findings.extend(check_terminal_reachable(view))
        findings.extend(check_reachable_from_start(view))

    findings.extend(check_required_subprocesses(graph, skeleton))
    findings.extend(check_known_subprocesses(graph, skeleton))
    findings.extend(check_needs_clarification(graph))

    return ValidationReport(findings=tuple(findings))
