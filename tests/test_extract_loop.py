"""Retry-loop tests for the extractor.

The loop is exercised through a fake :class:`~extractors.process.ModelCall`, so
these tests never touch the network and never construct a Strands agent.
"""

import pytest

from extractors.errors import ExtractionError, SchemaCallError
from extractors.process import extract
from ir.models import NodeType, ProcessGraph
from ir.skeleton import Skeleton
from tests.builders import branch, codes, edge, graph, node
from validators.report import FindingCode

SOURCE = "HCP can complete the PEF online via the portal or manually via fax."


def dangling_gateway_graph() -> ProcessGraph:
    """Structurally invalid: a decision with only one outgoing branch."""
    return graph(
        nodes=(
            node("start", NodeType.START, subprocess="intake"),
            node("gw_agrees", NodeType.GATEWAY, subprocess="off_label"),
            node("end", NodeType.TERMINAL, subprocess="onboarding"),
        ),
        edges=(edge("start", "gw_agrees"), branch("gw_agrees", "end", "prescriber agrees")),
    )


class FakeModel:
    """A scripted ModelCall that records the prompts it was given."""

    def __init__(self, *responses: ProcessGraph | Exception) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> ProcessGraph:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeModel called more times than it was scripted for")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def test_returns_on_the_first_attempt_when_structurally_valid(
    valid_graph: ProcessGraph, enrollment_skeleton: Skeleton
) -> None:
    """A sound graph costs exactly one model call."""
    fake = FakeModel(valid_graph)

    result = extract(SOURCE, enrollment_skeleton, call=fake)

    assert result.graph == valid_graph
    assert result.attempts == 1
    assert fake.call_count == 1


def test_first_prompt_carries_the_source_text(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """The opening turn is the source text; conventions live in the system prompt."""
    fake = FakeModel(valid_graph)

    extract(SOURCE, enrollment_skeleton, call=fake)

    assert SOURCE in fake.prompts[0]


def test_structural_failure_triggers_a_retry(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """A malformed graph is sent back for repair, and the repaired graph is returned."""
    fake = FakeModel(dangling_gateway_graph(), valid_graph)

    result = extract(SOURCE, enrollment_skeleton, call=fake)

    assert result.graph == valid_graph
    assert result.attempts == 2
    assert fake.call_count == 2


def test_retry_feeds_back_the_specific_defect(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """The repair turn names the offending node, not just 'that was invalid'."""
    fake = FakeModel(dangling_gateway_graph(), valid_graph)

    extract(SOURCE, enrollment_skeleton, call=fake)

    assert "gw_agrees" in fake.prompts[1]
    assert FindingCode.GATEWAY_BRANCHES in fake.prompts[1]


def test_resolution_findings_never_trigger_a_retry(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """Ambiguity passes through tagged. Retrying it would invite the model to invent."""
    fake = FakeModel(valid_graph)

    result = extract(SOURCE, enrollment_skeleton, call=fake)

    assert fake.call_count == 1
    assert FindingCode.MISSING_REQUIRED_SUBPROCESS in codes(result.report)
    assert result.report.is_structurally_valid


def test_exhausting_attempts_raises_with_the_last_report(enrollment_skeleton: Skeleton) -> None:
    """A graph that stays malformed is never emitted."""
    fake = FakeModel(*(dangling_gateway_graph() for _ in range(3)))

    with pytest.raises(ExtractionError) as caught:
        extract(SOURCE, enrollment_skeleton, call=fake, max_attempts=3)

    assert fake.call_count == 3
    assert caught.value.attempts == 3
    assert caught.value.report is not None
    assert FindingCode.GATEWAY_BRANCHES in codes(caught.value.report)


def test_schema_failure_is_retried(valid_graph: ProcessGraph, enrollment_skeleton: Skeleton) -> None:
    """A mechanical schema failure is a defect the model can fix, so it earns a retry."""
    fake = FakeModel(SchemaCallError("alternatives: Input should be a valid list"), valid_graph)

    result = extract(SOURCE, enrollment_skeleton, call=fake)

    assert result.graph == valid_graph
    assert result.attempts == 2
    assert "alternatives: Input should be a valid list" in fake.prompts[1]


def test_persistent_schema_failure_raises(enrollment_skeleton: Skeleton) -> None:
    """The loop is bounded even when the model never produces a parseable graph."""
    fake = FakeModel(*(SchemaCallError("bad shape") for _ in range(2)))

    with pytest.raises(ExtractionError) as caught:
        extract(SOURCE, enrollment_skeleton, call=fake, max_attempts=2)

    assert fake.call_count == 2
    assert caught.value.report is None


def test_max_attempts_must_be_positive(enrollment_skeleton: Skeleton) -> None:
    """A zero-attempt budget would silently emit nothing."""
    with pytest.raises(ValueError, match="max_attempts"):
        extract(SOURCE, enrollment_skeleton, call=FakeModel(), max_attempts=0)
