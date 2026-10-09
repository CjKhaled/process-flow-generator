"""The checks only a conversation can make.

:func:`validators.graph.validate` sees a graph and a skeleton and nothing else,
which is why it can require that a node names *a* lane but not that the lane
exists. A session holds what that validator lacks: the statements the user made,
the lanes learned from them, and the process definition. So these checks can hold
the conversation's two hardest promises mechanically:

* **Extraction is literal.** Every node and every branch must cite the statements
  it came from, and each quote is looked up in the statement it names. A step
  that rests on nothing the user said is rejected, not flagged.
* **Subprocesses come from the process definition**, never from the model.

Lanes are deliberately *not* checked here. A lane the extractor uses that the
session has not learned is a name the user's statements contained and the
interpreter missed, far more often than an invention -- and either way the right
response is to ask the user what it is, not to send the patch back. So an
unlisted lane is learned by :func:`session.orchestrator.learn_lanes` and becomes
a question. ``lanes`` stays in :func:`validate_session`'s signature because the
session is what this validator is a function of, and a lane rule that *is*
mechanical would belong here.

Kept apart from ``validate`` rather than folded into it, so the one-shot
pipeline's contract does not change: that path has no statements to check against
and its graphs carry no evidence.

All of these are structural. Each is a mechanical defect the model can see and
fix from the complaint, which is exactly what a repair turn is for.
"""

import re
from collections.abc import Collection, Iterator, Sequence

from ir.models import EdgeType, EvidenceRef, Node, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from knowledge.schemas import ProcessFile
from session.models import SessionLane, Statement
from session.patch import GraphPatch, RemoveEdge, RemoveNode
from validators.report import Finding, FindingCode, ValidationReport

_WHITESPACE = re.compile(r"\s+")
_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def validate_session(
    graph: ProcessGraph,
    corpus: Sequence[Statement],
    lanes: Sequence[SessionLane],
    process: ProcessFile,
) -> ValidationReport:
    """Check a session's graph against what the session knows.

    Args:
        graph: The master graph to check. Never modified.
        corpus: Every statement the user has made.
        lanes: The lanes the session has learned. Not checked against; see the
            module docstring.
        process: The process definition, for its declared subprocesses.

    Returns:
        A report holding only structural findings.
    """
    statements = {statement.id: statement for statement in corpus}
    findings: list[Finding] = []
    findings.extend(check_origin(graph))
    findings.extend(check_evidence_present(graph))
    findings.extend(check_evidence_found(graph, statements))
    findings.extend(check_scopes(graph, set(process.subprocess_ids)))
    return ValidationReport(findings=tuple(findings))


def normalise(text: str) -> str:
    """Text as quotes are compared: case folded, whitespace collapsed, typography flattened.

    A quote has to be the user's words, but it does not have to reproduce their
    curly apostrophes or their double spaces -- a model that straightens a quote
    mark has not invented anything.
    """
    return _WHITESPACE.sub(" ", text.translate(_TYPOGRAPHY)).strip().casefold()


def quote_found(quote: str, statement: Statement) -> bool:
    """Whether a quote appears in a statement's own text or in its restatement."""
    wanted = normalise(quote)
    if not wanted:
        return False
    return any(wanted in normalise(text) for text in (statement.raw_text, statement.restatement) if text)


def check_origin(graph: ProcessGraph) -> Iterator[Finding]:
    """A rule node is only ever the open terminal closing an outcome nobody stated."""
    for node in graph.nodes:
        if node.origin is NodeOrigin.RULE and not _is_open_terminal(node):
            yield Finding.of(
                FindingCode.RULE_ORIGIN_MISUSE,
                f"{node.type} node '{node.id}' ({node.label}) has origin 'rule', which is only for a "
                f"needs_clarification terminal closing an outcome the user did not state",
                node.id,
            )
        elif node.origin is NodeOrigin.SLICE:
            yield Finding.of(
                FindingCode.RULE_ORIGIN_MISUSE,
                f"node '{node.id}' ({node.label}) has origin 'slice', which is reserved for code",
                node.id,
            )


def check_evidence_present(graph: ProcessGraph) -> Iterator[Finding]:
    """Every source node, and every branch, cites something.

    The exemption is the branch leading to a rule terminal: by definition the
    user never stated that outcome, so there is nothing to quote.
    """
    rule_terminals = {node.id for node in graph.nodes if node.origin is NodeOrigin.RULE}
    for node in graph.nodes:
        if node.origin is NodeOrigin.SOURCE and not node.evidence:
            yield Finding.of(
                FindingCode.MISSING_EVIDENCE,
                f"{node.type} node '{node.id}' ({node.label}) cites no statement; every node the user's "
                f"words support must say which words",
                node.id,
            )
    for edge in graph.edges:
        if edge.type is EdgeType.BRANCH and not edge.evidence and edge.to_id not in rule_terminals:
            yield Finding.of(
                FindingCode.MISSING_EVIDENCE,
                f"branch {edge.from_id} -> {edge.to_id} cites no statement; a branch needs evidence unless "
                f"it leads to an origin 'rule' terminal",
                edge.from_id,
                edge.to_id,
            )


def check_evidence_found(graph: ProcessGraph, statements: dict[str, Statement]) -> Iterator[Finding]:
    """Every reference names a real statement, and its quote is in it."""
    for node in graph.nodes:
        for ref in node.evidence:
            problem = _problem(ref, statements)
            if problem:
                yield Finding.of(FindingCode.EVIDENCE_NOT_FOUND, f"node '{node.id}': {problem}", node.id)
    for edge in graph.edges:
        for ref in edge.evidence:
            problem = _problem(ref, statements)
            if problem:
                yield Finding.of(
                    FindingCode.EVIDENCE_NOT_FOUND,
                    f"edge {edge.from_id} -> {edge.to_id}: {problem}",
                    edge.from_id,
                    edge.to_id,
                )


def check_scopes(graph: ProcessGraph, subprocesses: Collection[str]) -> Iterator[Finding]:
    """Every subprocess tag is one the process declares."""
    known = ", ".join(sorted(subprocesses)) or "none"
    for node in graph.nodes:
        if node.subprocess and node.subprocess not in subprocesses:
            yield Finding.of(
                FindingCode.UNKNOWN_SCOPE,
                f"node '{node.id}' ({node.label}) is tagged subprocess '{node.subprocess}', which the "
                f"process does not declare ({known}); use a declared one or leave it null",
                node.id,
            )


def check_removal_reasons(patch: GraphPatch, corpus: Sequence[Statement]) -> Iterator[Finding]:
    """Every removal cites a statement that exists.

    Checked on the patch rather than the graph, because a removal leaves nothing
    behind to check: once applied, the reason for it is not in the graph at all.
    """
    known = {statement.id for statement in corpus}
    for operation in patch.operations:
        if isinstance(operation, RemoveNode | RemoveEdge):
            missing = [statement_id for statement_id in operation.reason_statement_ids if statement_id not in known]
            if missing:
                target = operation.id if isinstance(operation, RemoveNode) else operation.from_id
                yield Finding.of(
                    FindingCode.EVIDENCE_NOT_FOUND,
                    f"{operation.op} on '{target}' cites statement(s) {', '.join(missing)}, which do not exist",
                    target,
                )


def _is_open_terminal(node: Node) -> bool:
    return node.type is NodeType.TERMINAL and node.status is NodeStatus.NEEDS_CLARIFICATION


def _problem(ref: EvidenceRef, statements: dict[str, Statement]) -> str | None:
    """What is wrong with one reference, or None if it holds."""
    statement = statements.get(ref.statement_id)
    if statement is None:
        return f"cites statement '{ref.statement_id}', which does not exist"
    if not quote_found(ref.quote, statement):
        return (
            f'quotes "{ref.quote}" from {ref.statement_id}, but that statement does not contain those words; '
            f"copy the quote exactly from the statement's text"
        )
    return None
