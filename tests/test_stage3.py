"""Stage 3 orchestration, with the viewer's files stubbed out.

The assets are injected, so these exercise the whole stage -- finding stage 2's
diagram, reading the report beside it, writing the page -- without ``npm ci``.
"""

import json
from pathlib import Path

import pytest

from ir.process_config import OUTPUTS_DIRNAME
from pipelines.stage1 import REPORT_FILENAME
from pipelines.stage2 import DIAGRAM_FILENAME
from pipelines.stage3 import PAGE_FILENAME, main, run
from render.assets import AssetError, ViewerAssets
from tests.conftest import ENROLLMENT_DIR

DIAGRAM = "<definitions><task id='Node_gw_test_result' /></definitions>"

REPORT = {
    "findings": [
        {
            "code": "needs_clarification",
            "severity": "resolution",
            "message": "the source does not say what happens on the other branch",
            "node_ids": ["gw_test_result"],
        },
        {
            "code": "missing_swimlane",
            "severity": "structural",
            "message": "a defect stage 1 would never have written out",
            "node_ids": ["gw_test_result"],
        },
    ]
}


@pytest.fixture
def processes_root(tmp_path: Path) -> Path:
    """A process folder holding a stand-in diagram and report.

    The diagram is written rather than copied so these do not depend on stage 2
    having been run, and only ``metadata.yaml`` is taken from the real process --
    the display name is the one thing stage 3 reads from it.
    """
    outputs = tmp_path / "processes" / "enrollment" / OUTPUTS_DIRNAME
    outputs.mkdir(parents=True)
    (outputs.parent / "metadata.yaml").write_text(
        (ENROLLMENT_DIR / "metadata.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (outputs / DIAGRAM_FILENAME).write_text(DIAGRAM, encoding="utf-8")
    (outputs / REPORT_FILENAME).write_text(json.dumps(REPORT), encoding="utf-8")
    return tmp_path / "processes"


def test_run_writes_the_page(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    written = run("enrollment", processes_root, assets=viewer_assets)

    assert written == processes_root / "enrollment" / OUTPUTS_DIRNAME / PAGE_FILENAME
    assert DIAGRAM in written.read_text(encoding="utf-8").replace("\\u003c", "<")


def test_the_page_lists_only_the_open_questions(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    """The structural tier is stage 1's business, and a graph carrying one is never written."""
    rendered = run("enrollment", processes_root, assets=viewer_assets).read_text(encoding="utf-8")

    assert "the source does not say what happens on the other branch" in rendered
    assert "a defect stage 1 would never have written out" not in rendered


def test_the_display_name_comes_from_metadata(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    rendered = run("enrollment", processes_root, assets=viewer_assets).read_text(encoding="utf-8")

    assert "<h1>Intake &amp; Enrollment</h1>" in rendered


def test_a_missing_report_is_not_an_error(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    """A diagram is renderable whether or not the questions that came with it are still on disk."""
    (processes_root / "enrollment" / OUTPUTS_DIRNAME / REPORT_FILENAME).unlink()

    rendered = run("enrollment", processes_root, assets=viewer_assets).read_text(encoding="utf-8")

    assert "Open questions (0)" in rendered


def test_a_missing_diagram_names_stage_2(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    (processes_root / "enrollment" / OUTPUTS_DIRNAME / DIAGRAM_FILENAME).unlink()

    with pytest.raises(FileNotFoundError, match="stage 2"):
        run("enrollment", processes_root, assets=viewer_assets)


def test_a_missing_process_is_refused(processes_root: Path, viewer_assets: ViewerAssets) -> None:
    with pytest.raises(FileNotFoundError, match="no process directory"):
        run("onboarding", processes_root, assets=viewer_assets)


def test_main_reports_success(
    processes_root: Path, viewer_assets: ViewerAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pipelines.stage3.load_assets", lambda: viewer_assets)

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 0


def test_main_reports_an_unreadable_process(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipelines.stage3.load_assets", lambda: ViewerAssets(script="", styles=""))

    assert main(["--process", "onboarding", "--processes-root", str(processes_root)]) == 2


def test_main_reports_a_malformed_report(
    processes_root: Path, viewer_assets: ViewerAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pipelines.stage3.load_assets", lambda: viewer_assets)
    path = processes_root / "enrollment" / OUTPUTS_DIRNAME / REPORT_FILENAME
    path.write_text(json.dumps({"findings": [{"code": "no_such_code"}]}), encoding="utf-8")

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 2


def test_main_reports_a_missing_install(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> ViewerAssets:
        raise AssetError("cannot read bpmn-navigated-viewer.production.min.js")

    monkeypatch.setattr("pipelines.stage3.load_assets", missing)

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 1
