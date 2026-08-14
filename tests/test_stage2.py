"""Stage 2 orchestration, with the layouter stubbed out.

The layouter is injected, so these exercise the whole stage -- reading stage 1's
graph, building the document, writing the result -- without Node installed.
Nothing here asserts geometry: the stub returns its input unchanged, because
geometry is the layouter's to produce and the integration suite is where it is
checked.
"""

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bpmn.autolayout import Layouter, LayoutError
from bpmn.document import BPMN_NS
from ir.models import NodeType, ProcessGraph
from pipelines.stage1 import GRAPH_FILENAME
from pipelines.stage2 import DIAGRAM_FILENAME, main, run
from tests.builders import edge, graph, node
from tests.conftest import ENROLLMENT_DIR, echo_layouter


@pytest.fixture
def processes_root(tmp_path: Path) -> Path:
    """A throwaway copy of the real enrollment process folder, graph included."""
    root = tmp_path / "processes"
    shutil.copytree(ENROLLMENT_DIR, root / "enrollment")
    (root / "enrollment" / "outputs" / DIAGRAM_FILENAME).unlink(missing_ok=True)
    return root


def write_graph(processes_root: Path, process: ProcessGraph) -> None:
    """Replace the copied folder's stage-1 output."""
    path = processes_root / "enrollment" / "outputs" / GRAPH_FILENAME
    path.write_text(json.dumps(process.model_dump(mode="json")), encoding="utf-8")


def test_run_writes_the_diagram(processes_root: Path, layouter: Layouter) -> None:
    written = run("enrollment", processes_root, layout=layouter)

    assert written == processes_root / "enrollment" / "outputs" / DIAGRAM_FILENAME
    assert written.is_file()


def test_what_reaches_the_layouter_is_parseable_bpmn(processes_root: Path) -> None:
    """The stage's real output is its input to the layouter, so that is what to check."""
    seen: list[str] = []

    def capture(xml: str) -> str:
        seen.append(xml)
        return xml

    run("enrollment", processes_root, layout=capture)

    assert ET.fromstring(seen[0]).tag == f"{{{BPMN_NS}}}definitions"


def test_the_layouters_output_is_what_gets_written(processes_root: Path) -> None:
    """The stage must not post-process the geometry it asked for."""

    def replace(xml: str) -> str:
        return "<laid-out/>"

    written = run("enrollment", processes_root, layout=replace)

    assert written.read_text(encoding="utf-8") == "<laid-out/>"


def test_ids_come_from_the_metadata_not_the_graphs_own_label(processes_root: Path, layouter: Layouter) -> None:
    """A model may name the graph anything; the folder and metadata are authoritative."""
    write_graph(
        processes_root,
        graph(
            (node("a", NodeType.START), node("b", NodeType.TERMINAL)),
            (edge("a", "b"),),
            name="Some Label The Model Chose",
        ),
    )

    text = run("enrollment", processes_root, layout=layouter).read_text(encoding="utf-8")
    assert 'id="Process_enrollment"' in text
    assert "Some_Label_The_Model_Chose" not in text


def test_an_undeclared_actor_is_refused(processes_root: Path, layouter: Layouter) -> None:
    """Stage 1 cannot catch this: the validator never sees metadata.yaml."""
    write_graph(
        processes_root,
        graph(
            (node("a", NodeType.START, actor="Acme Corp"), node("b", NodeType.TERMINAL, actor="CM360")),
            (edge("a", "b"),),
        ),
    )

    with pytest.raises(ValueError, match="Acme Corp"):
        run("enrollment", processes_root, layout=layouter)


def test_a_missing_process_folder_is_reported(tmp_path: Path, layouter: Layouter) -> None:
    with pytest.raises(FileNotFoundError, match="no process directory"):
        run("nonexistent", tmp_path, layout=layouter)


def test_a_missing_stage_one_graph_says_to_run_stage_one(processes_root: Path, layouter: Layouter) -> None:
    (processes_root / "enrollment" / "outputs" / GRAPH_FILENAME).unlink()

    with pytest.raises(FileNotFoundError, match="run stage 1"):
        run("enrollment", processes_root, layout=layouter)


def test_nothing_is_written_when_the_layouter_fails(processes_root: Path) -> None:
    """A half-written diagram is worse than none; the failure must precede the write."""

    def broken(xml: str) -> str:
        raise LayoutError("the layouter rejected the diagram")

    with pytest.raises(LayoutError):
        run("enrollment", processes_root, layout=broken)

    assert not (processes_root / "enrollment" / "outputs" / DIAGRAM_FILENAME).exists()


def test_main_returns_zero_on_success(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipelines.stage2.subprocess_layouter", lambda *_args, **_kwargs: echo_layouter)

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 0


def test_main_returns_two_for_a_missing_process(tmp_path: Path) -> None:
    assert main(["--process", "nope", "--processes-root", str(tmp_path)]) == 2


def test_main_returns_two_for_an_undeclared_actor(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipelines.stage2.subprocess_layouter", lambda *_args, **_kwargs: echo_layouter)
    write_graph(
        processes_root,
        graph(
            (node("a", NodeType.START, actor="Acme Corp"), node("b", NodeType.TERMINAL, actor="CM360")),
            (edge("a", "b"),),
        ),
    )

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 2


def test_main_returns_one_when_the_layout_fails(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(xml: str) -> str:
        raise LayoutError("the layouter rejected the diagram")

    monkeypatch.setattr("pipelines.stage2.subprocess_layouter", lambda *_args, **_kwargs: broken)

    assert main(["--process", "enrollment", "--processes-root", str(processes_root)]) == 1


def test_stage_two_never_loads_the_model_settings(processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It calls no model, so requiring an API key would be a startup failure for no reason."""

    def refuse() -> None:
        raise AssertionError("stage 2 must not read the model settings")

    monkeypatch.setattr("utils.settings.load_settings", refuse)

    assert run("enrollment", processes_root, layout=echo_layouter).is_file()
