"""Everything stage 3 reads from disk: the built bundle, the stylesheets, the shell.

Two different roots, for two different reasons. The script is **ours**, built
from ``js/src/`` by esbuild, because the page needs bpmn-js plus this project's
own modules compiled together. The stylesheets are bpmn-js's, read straight from
``node_modules`` -- they need no compiling, and Python is what assembles the
page.


The page is written as a **single self-contained file**, so the viewer bundle and
its stylesheets are inlined rather than linked. That is not a preference for big
files: the page is opened with Live Server, or over ``file://``, from whatever
folder the reader happened to point at, and any relative ``../../node_modules``
path is broken by a different choice of root. Inlining removes the question.

It is affordable because the icon font is already a base64 data URI inside
``bpmn-embedded.css`` -- so nothing else has to be embedded by hand, and the
whole page lands around 730 KB, most of it :data:`BUNDLE`.

This module holds stage 3's only file reads. :mod:`render.page` is pure string
assembly, and stays that way by being handed what it needs.
"""

import base64
from dataclasses import dataclass
from pathlib import Path

JS_ROOT = Path(__file__).resolve().parent.parent / "js"

BUNDLE = JS_ROOT / "dist" / "pfg-viewer.js"
"""Our own bundle: bpmn-js plus the modules in ``js/src/``, built by esbuild.

Not one of bpmn-js's prebuilt files. The page needs a modeler *and* this
project's own renderer, palette and read-only gate, and those are ES modules
that have to be compiled in -- which is what the build step exists for. The
prebuilt files are sealed, and reach nothing but what their single global
exposes.

Built rather than committed, because it is derived from ``package-lock.json``
and ``src/`` and would otherwise be a large binary artifact to keep in step by
hand.
"""

STYLES_DIR = JS_ROOT / "node_modules" / "bpmn-js" / "dist"
"""Where the stylesheets come from: bpmn-js as installed, not as bundled.

The CSS is not part of the bundle. Python assembles the page, so Python reads
the stylesheets and inlines them, and esbuild is left doing only the job it is
good at.
"""

STYLESHEETS = (
    "assets/diagram-js.css",
    "assets/bpmn-js.css",
    "assets/bpmn-font/css/bpmn-embedded.css",
)
"""Concatenated in this order: the canvas, then BPMN's own rules, then the icon font."""

FONTS_DIR = JS_ROOT / "node_modules" / "@fontsource-variable"
"""Where the two typefaces come from: installed with the viewer, never fetched by the page."""

FONTS = (
    ("Figtree", "figtree/files/figtree-latin-wght-normal.woff2", "300 900"),
    ("JetBrains Mono", "jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2", "100 800"),
)
"""Family name, file under :data:`FONTS_DIR`, and the weight range the variable file covers.

The Latin subset only. The page is one self-contained file, so each typeface is
inlined as a data URI, and the full character set would cost several times as
much for glyphs a process diagram's chrome never uses.
"""

TEMPLATE = Path(__file__).resolve().parent / "template.html"


class AssetError(RuntimeError):
    """A file the page is built from is not on disk."""


@dataclass(frozen=True)
class ViewerAssets:
    """The viewer's JavaScript and stylesheets, as text ready to inline."""

    script: str
    styles: str


def load_assets(bundle: Path = BUNDLE, styles_dir: Path = STYLES_DIR, fonts_dir: Path = FONTS_DIR) -> ViewerAssets:
    """Read the built bundle, bpmn-js's stylesheets and the page's two typefaces.

    Args:
        bundle: Our esbuild output. Overridden in tests, which inline a stub
            rather than half a megabyte of vendor code.
        styles_dir: The ``dist/`` directory of an installed bpmn-js.
        fonts_dir: The installed ``@fontsource-variable`` packages.

    Returns:
        The script, and one stylesheet: the typefaces as ``@font-face`` rules
        with the files inlined, then bpmn-js's own.

    Raises:
        AssetError: If either is missing. The two carry different remedies on
            purpose -- a missing bundle means the *build* has not been run,
            which ``npm ci`` alone will not fix, and that is the mistake most
            likely to be made after a fresh clone.
    """
    script = _read(bundle, f"run `npm ci --prefix {JS_ROOT}` then `npm run build --prefix {JS_ROOT}`")
    install = f"run `npm ci --prefix {JS_ROOT}`"
    faces = [_font_face(family, fonts_dir / name, weights, install) for family, name, weights in FONTS]
    styles = "\n".join([*faces, *(_read(styles_dir / name, install) for name in STYLESHEETS)])
    return ViewerAssets(script=script, styles=styles)


def _font_face(family: str, path: Path, weights: str, remedy: str) -> str:
    """One typeface as a rule the page can use with nothing to download.

    Inlined for the reason everything else is: the page is opened from wherever
    the reader keeps it, with no server beside it to ask for a font file.
    """
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as error:
        raise AssetError(f"cannot read {path}; {remedy}") from error
    return (
        f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {weights}; "
        f"font-display: swap; src: url(data:font/woff2;base64,{encoded}) format('woff2-variations'); }}"
    )


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
