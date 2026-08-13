"""Pipeline orchestration tests.

The model is injected, so these exercise the whole of stage 1 -- reading the real
enrollment inputs, validating, writing the artifacts -- without a network.
"""

import json
import shutil
from pathlib import Path

import pytest

from extractors.errors import ExtractionError
from extractors.process import ModelCall
from ir.models import NodeType, ProcessGraph
from pipelines.stage1 import GRAPH_FILENAME, REPORT_FILENAME, main, run
from tests.builders import branch, codes, edge, graph, node
from tests.conftest import ENROLLMENT_DIR
from validators.report import FindingCode, ValidationReport


@pytest.fixture
def processes_root(tmp_path: Path) -> Path:
    """A throwaway copy of the real enrollment process folder."""
    root = tmp_path / "processes"
    shutil.copytree(ENROLLMENT_DIR, root / "enrollment")
    shutil.rmtree(root / "enrollment" / "outputs", ignore_errors=True)
    return root


def constant_call(result: ProcessGraph) -> ModelCall:
    """A ModelCall that always returns the same graph, whatever it is asked."""

    def call(prompt: str) -> ProcessGraph:
        return result

    return call


def broken_graph() -> ProcessGraph:
    return graph(
        nodes=(
            node("start", NodeType.START),
            node("gw", NodeType.GATEWAY),
            node("end", NodeType.TERMINAL),
        ),
        edges=(edge("start", "gw"), branch("gw", "end", "prescriber agrees")),
    )


def test_run_writes_both_artifacts(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """A successful run leaves a graph and a report on disk."""
    result = run("enrollment", processes_root, call=constant_call(valid_graph))

    outputs = processes_root / "enrollment" / "outputs"
    assert result.graph == valid_graph
    assert (outputs / GRAPH_FILENAME).is_file()
    assert (outputs / REPORT_FILENAME).is_file()


def test_written_graph_reparses_and_revalidates(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The artifact on disk is a faithful, still-valid ProcessGraph."""
    run("enrollment", processes_root, call=constant_call(valid_graph))
    written = (processes_root / "enrollment" / "outputs" / GRAPH_FILENAME).read_text(encoding="utf-8")

    assert ProcessGraph.model_validate_json(written) == valid_graph


def test_written_report_records_the_open_questions(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The absent missing_info subprocess reaches disk as a finding."""
    run("enrollment", processes_root, call=constant_call(valid_graph))
    written = (processes_root / "enrollment" / "outputs" / REPORT_FILENAME).read_text(encoding="utf-8")
    report = ValidationReport.model_validate_json(written)

    assert FindingCode.MISSING_REQUIRED_SUBPROCESS in codes(report)
    assert any("missing_info" in finding.message for finding in report.resolution)


def test_the_model_receives_the_real_source_text(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The enrollment description on disk is what gets extracted."""
    seen: list[str] = []

    def call(prompt: str) -> ProcessGraph:
        seen.append(prompt)
        return valid_graph

    run("enrollment", processes_root, call=call)

    assert "HCP can complete the PEF online via the portal" in seen[0]


def test_structural_failure_writes_nothing(processes_root: Path) -> None:
    """A graph that fails the hard tier never reaches outputs/."""
    with pytest.raises(ExtractionError):
        run("enrollment", processes_root, call=constant_call(broken_graph()), max_attempts=2)

    outputs = processes_root / "enrollment" / "outputs"
    assert not (outputs / GRAPH_FILENAME).exists()
    assert not (outputs / REPORT_FILENAME).exists()


def test_unknown_process_is_reported(processes_root: Path) -> None:
    """A typo in the process name fails before anything is read."""
    with pytest.raises(FileNotFoundError, match="no process directory"):
        run("enrolment", processes_root)


def test_mismatched_process_names_fail_before_the_model_is_called(
    processes_root: Path, valid_graph: ProcessGraph
) -> None:
    """A half-edited folder copy is caught rather than extracted under the wrong name."""
    metadata = processes_root / "enrollment" / "metadata.yaml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("process_name: enrollment", "process_name: onboarding"),
        encoding="utf-8",
    )
    called = False

    def call(prompt: str) -> ProcessGraph:
        nonlocal called
        called = True
        return valid_graph

    with pytest.raises(ValueError, match="metadata.yaml says 'onboarding'"):
        run("enrollment", processes_root, call=call)

    assert not called


def test_a_zero_attempt_budget_is_rejected(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """An explicit 0 reaches the guard in extract() instead of silently becoming the default."""
    with pytest.raises(ValueError, match="max_attempts"):
        run("enrollment", processes_root, call=constant_call(valid_graph), max_attempts=0)


def test_main_reports_a_mismatched_process_name(processes_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A name mismatch is a configuration error, so it exits 2 with no traceback."""
    skeleton = processes_root / "enrollment" / "skeleton.json"
    skeleton.write_text(
        skeleton.read_text(encoding="utf-8").replace('"process_name": "enrollment"', '"process_name": "onboarding"'),
        encoding="utf-8",
    )

    exit_code = main(["--process", "enrollment", "--processes-root", str(processes_root)])

    assert exit_code == 2
    assert "skeleton.json says 'onboarding'" in capsys.readouterr().err


def test_main_reports_a_missing_api_key_without_a_traceback(
    processes_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing credential is a configuration error, surfaced as one."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(processes_root)

    exit_code = main(["--process", "enrollment", "--processes-root", str(processes_root)])

    assert exit_code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_main_reports_an_unknown_process(processes_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An unreadable process exits 2, distinct from an extraction failure."""
    exit_code = main(["--process", "nope", "--processes-root", str(processes_root)])

    assert exit_code == 2
    assert "no process directory" in capsys.readouterr().err


def test_graph_json_is_human_readable(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The artifact is indented and uses the wire vocabulary, so it can be reviewed by eye."""
    run("enrollment", processes_root, call=constant_call(valid_graph))
    raw = (processes_root / "enrollment" / "outputs" / GRAPH_FILENAME).read_text(encoding="utf-8")

    assert raw.startswith("{\n")
    assert json.loads(raw)["nodes"][0]["type"] == "start"
