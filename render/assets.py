"""Everything stage 3 reads from disk: the viewer's files, and the page shell.

The page is written as a **single self-contained file**, so the viewer bundle and
its stylesheets are inlined rather than linked. That is not a preference for big
files: the page is opened with Live Server, or over ``file://``, from whatever
folder the reader happened to point at, and any relative ``../../node_modules``
path is broken by a different choice of root. Inlining removes the question.

It is affordable because the icon font is already a base64 data URI inside
``bpmn-embedded.css`` -- so nothing else has to be embedded by hand, and the
whole page lands around 730 KB, most of it :data:`VIEWER_JS`.

This module holds stage 3's only file reads. :mod:`render.page` is pure string
assembly, and stays that way by being handed what it needs.
"""

from dataclasses import dataclass
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / "js" / "node_modules" / "bpmn-js" / "dist"
"""The vendored bpmn-js distribution, installed by ``npm ci --prefix js``."""

JS_ROOT = DIST.parents[2]

VIEWER_JS = "bpmn-modeler.production.min.js"
"""The modeler, for the page's session-only Edit mode.

Three times the navigated viewer's size -- about 570 KB against 190 KB, which is
most of why a page is now nearer 730 KB than 350 KB. The viewer bundle cannot be
used instead: the machinery for dragging a shape lives in modules it does not
contain, and taking only those would need a bundler this project does not have.

The page opens with editing off and builds that state itself, since a modeler is
live from construction. Nothing it produces is ever saved, so an edited diagram
can never disagree with ``graph.json`` on disk.
"""

STYLESHEETS = (
    "assets/diagram-js.css",
    "assets/bpmn-js.css",
    "assets/bpmn-font/css/bpmn-embedded.css",
)
"""Concatenated in this order: the canvas, then BPMN's own rules, then the icon font."""

TEMPLATE = Path(__file__).resolve().parent / "template.html"


class AssetError(RuntimeError):
    """A file the page is built from is not on disk."""


@dataclass(frozen=True)
class ViewerAssets:
    """The viewer's JavaScript and stylesheets, as text ready to inline."""

    script: str
    styles: str


def load_assets(dist: Path = DIST) -> ViewerAssets:
    """Read the bpmn-js distribution.

    Args:
        dist: The ``dist/`` directory of an installed bpmn-js. Overridden in
            tests, which inline stubs rather than 300 KB of vendor code.

    Returns:
        The script and the concatenated stylesheets.

    Raises:
        AssetError: If any of them is missing, naming the command that installs them.
    """
    install = f"run `npm ci --prefix {JS_ROOT}`"
    script = _read(dist / VIEWER_JS, install)
    styles = "\n".join(_read(dist / name, install) for name in STYLESHEETS)
    return ViewerAssets(script=script, styles=styles)


def load_template(path: Path = TEMPLATE) -> str:
    """Read the page shell.

    Args:
        path: The template file.

    Returns:
        Its text, sentinels unsubstituted.

    Raises:
        AssetError: If it is missing. Unlike the viewer, this one ships with the
            project, so its absence is a broken checkout and no install fixes it.
    """
    return _read(path, "the page template ships with the project")


def _read(path: Path, remedy: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise AssetError(f"cannot read {path}; {remedy}") from error
