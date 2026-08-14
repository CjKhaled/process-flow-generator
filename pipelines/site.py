"""Build the hosted page: the viewer, the picker, and no diagram yet.

The static half of the demo. Where stage 3 writes a page with one process's
result already in it, this writes the page that asks for one -- the same shell,
the same viewer, the same panel, and a form in front of it. What it does not
contain is any pipeline: the run happens in :mod:`api`, and this page's job is
to ask for it and draw the answer.

It is a build step rather than a committed file for the same reason stage 3's
output is: it is 90% vendored viewer, and it is regenerated in a second.
"""

import argparse
import logging
import sys
from pathlib import Path

from ir.process_config import list_processes
from render import page
from render.assets import AssetError, ViewerAssets, load_assets, load_template

logger = logging.getLogger(__name__)

DEFAULT_PROCESSES_ROOT = Path(__file__).resolve().parent.parent / "processes"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "site"
PAGE_FILENAME = "index.html"
NOJEKYLL_FILENAME = ".nojekyll"


def run(
    api_base: str,
    out_dir: Path = DEFAULT_OUT,
    processes_root: Path = DEFAULT_PROCESSES_ROOT,
    *,
    assets: ViewerAssets | None = None,
) -> Path:
    """Build the site.

    Args:
        api_base: Where the pipeline service lives, e.g.
            ``https://pfg-api.onrender.com``. Empty means same-origin, which is
            what the one-URL deployment wants: the service serves this page too.
        out_dir: Where to write it.
        processes_root: Where the process folders live; each one becomes an
            option in the picker.
        assets: The viewer's files. Defaults to the vendored install.

    Returns:
        The path of the page written.

    Raises:
        FileNotFoundError: If no process could be found to offer.
        render.assets.AssetError: If the viewer's files are not installed.
    """
    processes = list_processes(processes_root)
    if not processes:
        raise FileNotFoundError(f"no processes under {processes_root}; there would be nothing to pick")

    rendered = page.build_app(
        assets or load_assets(),
        load_template(),
        [(process.name, process.display_name) for process in processes],
        api_base,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / PAGE_FILENAME
    destination.write_text(rendered, encoding="utf-8")
    # Without this, GitHub Pages runs the output through Jekyll, which discards
    # files and folders whose names begin with an underscore.
    (out_dir / NOJEKYLL_FILENAME).write_text("", encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Returns:
        0 on success, 1 if the page could not be built, 2 if there was nothing
        to build it from.
    """
    parser = argparse.ArgumentParser(description="Build the hosted demo page.")
    parser.add_argument(
        "--api-base",
        required=True,
        help="Base URL of the pipeline service. Pass '' for same-origin.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Directory to write the site into.")
    parser.add_argument(
        "--processes-root",
        type=Path,
        default=DEFAULT_PROCESSES_ROOT,
        help="Directory holding the process folders.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)

    try:
        written = run(args.api_base, args.out, args.processes_root)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except AssetError as error:
        print(f"error: {error}", file=sys.stderr)
        print("nothing written; the page could not be built.", file=sys.stderr)
        return 1

    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
