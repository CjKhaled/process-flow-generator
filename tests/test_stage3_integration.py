"""Stage 3 against the real bpmn-js install. Skipped when ``npm ci`` has not run.

What only the real assets can show is that the page is genuinely self-contained:
that the viewer bundle is present in full and that the icon font came inlined
with the stylesheets, so nothing is fetched when the page is opened.

Whether it *draws* is not asserted here, because no browser runs in this suite.
That is checked by opening the file, which is a manual step and is left an
honest gap rather than a fake one.
"""

from pathlib import Path

import pytest

from pipelines.stage2 import DIAGRAM_FILENAME
from pipelines.stage3 import PAGE_FILENAME, run
from render.assets import load_assets
from tests.conftest import ENROLLMENT_DIR, requires_node

pytestmark = requires_node


def test_the_real_assets_load() -> None:
    assets = load_assets()

    assert "BpmnJS" in assets.script
    assert "@font-face" in assets.styles
    assert "data:application/octet-stream;" in assets.styles, "the icon font should be inlined, not linked"


def test_the_page_holds_everything_it_needs(tmp_path: Path) -> None:
    """Built from enrollment's real stage-2 output, if stage 2 has been run."""
    diagram = ENROLLMENT_DIR / "outputs" / DIAGRAM_FILENAME
    if not diagram.is_file():
        pytest.skip("run stage 2 for enrollment first")

    root = tmp_path / "processes"
    (root / "enrollment" / "outputs").mkdir(parents=True)
    for source in (ENROLLMENT_DIR / "metadata.yaml", diagram, ENROLLMENT_DIR / "outputs" / "validation.json"):
        (root / "enrollment" / source.relative_to(ENROLLMENT_DIR)).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )

    written = run("enrollment", root)
    rendered = written.read_text(encoding="utf-8")

    assert written.name == PAGE_FILENAME
    assert "<link" not in rendered and "<script src" not in rendered, "nothing should be fetched at view time"
    assert "<!--PFG:" not in rendered
    assert len(rendered) > 300_000, "the viewer and its stylesheets should be inlined in full"
