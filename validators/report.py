"""What the validator returns.

The report is data, not a verdict acted upon in place: ``validate`` never mutates
the graph it inspects. The pipeline writes the report alongside the graph so a
human can see exactly what was tagged and why.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """Which tier a finding belongs to."""

    STRUCTURAL = "structural"
    """Hard. The graph is malformed and must not be emitted."""

    RESOLUTION = "resolution"
    """Soft. The graph is well formed but a human needs to resolve something."""


class FindingCode(StrEnum):
    """Every defect the validator knows how to name."""

    # Structural tier.
    DUPLICATE_NODE_ID = "duplicate_node_id"
    DANGLING_EDGE_REF = "dangling_edge_ref"
    START_NODE_COUNT = "start_node_count"
    GATEWAY_BRANCHES = "gateway_branches"
    ORPHAN_NODE = "orphan_node"
    TERMINAL_UNREACHABLE = "terminal_unreachable"
    UNREACHABLE_FROM_START = "unreachable_from_start"
    MALFORMED_ANNOTATION = "malformed_annotation"
    MISSING_CLARIFICATION_DETAIL = "missing_clarification_detail"

    # Resolution tier.
    MISSING_REQUIRED_SUBPROCESS = "missing_required_subprocess"
    UNKNOWN_SUBPROCESS = "unknown_subprocess"
    NEEDS_CLARIFICATION = "needs_clarification"


_SEVERITY_BY_CODE: dict[FindingCode, Severity] = {
    FindingCode.DUPLICATE_NODE_ID: Severity.STRUCTURAL,
    FindingCode.DANGLING_EDGE_REF: Severity.STRUCTURAL,
    FindingCode.START_NODE_COUNT: Severity.STRUCTURAL,
    FindingCode.GATEWAY_BRANCHES: Severity.STRUCTURAL,
    FindingCode.ORPHAN_NODE: Severity.STRUCTURAL,
    FindingCode.TERMINAL_UNREACHABLE: Severity.STRUCTURAL,
    FindingCode.UNREACHABLE_FROM_START: Severity.STRUCTURAL,
    FindingCode.MALFORMED_ANNOTATION: Severity.STRUCTURAL,
    FindingCode.MISSING_CLARIFICATION_DETAIL: Severity.STRUCTURAL,
    FindingCode.MISSING_REQUIRED_SUBPROCESS: Severity.RESOLUTION,
    FindingCode.UNKNOWN_SUBPROCESS: Severity.RESOLUTION,
    FindingCode.NEEDS_CLARIFICATION: Severity.RESOLUTION,
}


class Finding(BaseModel):
    """One thing the validator noticed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: FindingCode
    severity: Severity
    message: str = Field(min_length=1, description="Human-readable explanation, naming the nodes involved.")
    node_ids: tuple[str, ...] = Field(default=(), description="The nodes this finding is about, if any.")

    @classmethod
    def of(cls, code: FindingCode, message: str, *node_ids: str) -> "Finding":
        """Build a finding, deriving severity from the code so the two cannot diverge."""
        return cls(code=code, severity=_SEVERITY_BY_CODE[code], message=message, node_ids=node_ids)


class ValidationReport(BaseModel):
    """The outcome of validating one graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[Finding, ...] = ()

    @property
    def structural(self) -> tuple[Finding, ...]:
        """Findings that make the graph unfit to emit."""
        return tuple(f for f in self.findings if f.severity is Severity.STRUCTURAL)

    @property
    def resolution(self) -> tuple[Finding, ...]:
        """Findings a human should resolve, which do not block emission."""
        return tuple(f for f in self.findings if f.severity is Severity.RESOLUTION)

    @property
    def is_structurally_valid(self) -> bool:
        """Whether the graph passes the hard tier and may be emitted."""
        return not self.structural

    def summary(self) -> str:
        """A one-line-per-finding rendering, for CLI output and repair prompts."""
        if not self.findings:
            return "no findings"
        return "\n".join(f"[{f.severity}] {f.code}: {f.message}" for f in self.findings)
