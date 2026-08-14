"""The hosted page's build step, with the viewer's files stubbed out."""

from pathlib import Path

import pytest

from pipelines.site import NOJEKYLL_FILENAME, PAGE_FILENAME, main, run
from render.assets import AssetError, ViewerAssets
from tests.conftest import ENROLLMENT_DIR

API = "https://pfg-api.onrender.com"


@pytest.fixture
def processes_root(tmp_path: Path) -> Path:
    """Two processes, so the picker has something to choose between."""
    root = tmp_path / "processes"
    for name in ("enrollment", "copay"):
        (root / name).mkdir(parents=True)
        (root / name / "metadata.yaml").write_text(
            (ENROLLMENT_DIR / "metadata.yaml").read_text(encoding="utf-8").replace("Intake & Enrollment", name.title()),
            encoding="utf-8",
        )
    return root


def test_run_writes_the_page(tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets) -> None:
    written = run(API, tmp_path / "site", processes_root, assets=viewer_assets)

    assert written == tmp_path / "site" / PAGE_FILENAME
    assert API in written.read_text(encoding="utf-8")


def test_every_process_reaches_the_picker(tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets) -> None:
    rendered = run(API, tmp_path / "site", processes_root, assets=viewer_assets).read_text(encoding="utf-8")

    assert '<option value="enrollment">' in rendered
    assert '<option value="copay">' in rendered


def test_jekyll_is_turned_off(tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets) -> None:
    """Pages would otherwise process the output and drop anything beginning with an underscore."""
    run(API, tmp_path / "site", processes_root, assets=viewer_assets)

    assert (tmp_path / "site" / NOJEKYLL_FILENAME).is_file()


def test_a_folder_with_no_processes_is_refused(tmp_path: Path, viewer_assets: ViewerAssets) -> None:
    """A picker with nothing in it is a page nobody can use."""
    empty = tmp_path / "nothing"
    empty.mkdir()

    with pytest.raises(FileNotFoundError, match="nothing to pick"):
        run(API, tmp_path / "site", empty, assets=viewer_assets)


def test_a_malformed_process_does_not_stop_the_others(
    tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets
) -> None:
    """A half-copied folder is a reason to skip that process, not to fail the build."""
    (processes_root / "broken").mkdir()
    (processes_root / "broken" / "metadata.yaml").write_text("process_name: []", encoding="utf-8")

    rendered = run(API, tmp_path / "site", processes_root, assets=viewer_assets).read_text(encoding="utf-8")

    assert '<option value="enrollment">' in rendered
    assert '<option value="broken">' not in rendered


def test_main_reports_success(
    tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pipelines.site.load_assets", lambda: viewer_assets)
    argv = ["--api-base", API, "--out", str(tmp_path / "site"), "--processes-root", str(processes_root)]

    assert main(argv) == 0


def test_main_accepts_a_same_origin_build(
    tmp_path: Path, processes_root: Path, viewer_assets: ViewerAssets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty base is a deployment, not a mistake: the API serves the page itself."""
    monkeypatch.setattr("pipelines.site.load_assets", lambda: viewer_assets)
    argv = ["--api-base", "", "--out", str(tmp_path / "site"), "--processes-root", str(processes_root)]

    assert main(argv) == 0


def test_main_reports_nothing_to_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pipelines.site.load_assets", lambda: ViewerAssets(script="", styles=""))
    empty = tmp_path / "nothing"
    empty.mkdir()
    argv = ["--api-base", API, "--out", str(tmp_path / "site"), "--processes-root", str(empty)]

    assert main(argv) == 2


def test_main_reports_a_missing_install(tmp_path: Path, processes_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> ViewerAssets:
        raise AssetError("cannot read bpmn-navigated-viewer.production.min.js")

    monkeypatch.setattr("pipelines.site.load_assets", missing)
    argv = ["--api-base", API, "--out", str(tmp_path / "site"), "--processes-root", str(processes_root)]

    assert main(argv) == 1
