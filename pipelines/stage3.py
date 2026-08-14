"""Stage 3 orchestrator: a BPMN file on disk -> a page a human can open.

One run: read ``processes/<name>/outputs/diagram.bpmn`` and, if it is there, the
validation report beside it -> write ``processes/<name>/outputs/diagram.html``.
Deterministic, like stage 2: no model, no network, and nothing read at view time
either, since the viewer is inlined into the page.

The report is optional. A diagram is renderable whether or not the questions
that came with it are still on disk, and refusing to draw one because a sibling
file was deleted would be a rule with nothing behind it. Stage 2's output is not
optional: without it there is nothing to render, and the error says which stage
to run.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from ir.process_config import OUTPUTS_DIRNAME, load_process_config
from pipelines.stage1 import REPORT_FILENAME
from pipelines.stage2 import DIAGRAM_FILENAME
from render import page
from render.assets import AssetError, ViewerAssets, load_assets, load_template
from validators.report import Finding, ValidationReport

logger = logging.getLogger(__name__)

DEFAULT_PROCESSES_ROOT = Path(__file__).resolve().parent.parent / "processes"
PAGE_FILENAME = "diagram.html"


def run(
    process_name: str,
    processes_root: Path = DEFAULT_PROCESSES_ROOT,
    *,
    assets: ViewerAssets | None = None,
) -> Path:
    """Run stage 3 for one process.

    Args:
        process_name: The folder name under ``processes/``.
        processes_root: Where the process folders live.
        assets: The viewer's files. Defaults to the vendored install; injecting
            stubs lets the orchestration be exercised without ``npm ci``.

    Returns:
        The path written.

    Raises:
        FileNotFoundError: If the process folder or stage 2's diagram is missing.
        pydantic.ValidationError: If the report on disk does not match the schema.
        render.assets.AssetError: If the viewer's files are not installed.
    """
    process_dir = processes_root / process_name
    if not process_dir.is_dir():
        raise FileNotFoundError(f"no process directory at {process_dir}")

    diagram_path = process_dir / OUTPUTS_DIRNAME / DIAGRAM_FILENAME
    if not diagram_path.is_file():
        raise FileNotFoundError(f"no diagram at {diagram_path}; run stage 2 for '{process_name}' first")

    config = load_process_config(process_dir)
    rendered = page.build(
        diagram_path.read_text(encoding="utf-8"),
        _open_questions(process_dir / OUTPUTS_DIRNAME / REPORT_FILENAME),
        config.display_name,
        assets or load_assets(),
        load_template(),
    )

    destination = process_dir / OUTPUTS_DIRNAME / PAGE_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return destination


def _open_questions(report_path: Path) -> tuple[Finding, ...]:
    """The resolution tier of the report beside the diagram, or nothing if it is absent."""
    if not report_path.is_file():
        logger.warning("no report at %s; the page will show no open questions", report_path)
        return ()
    report = ValidationReport.model_validate(json.loads(report_path.read_text(encoding="utf-8")))
    return report.resolution


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Returns:
        0 on success, 1 if the page could not be built, 2 if the process could
        not be read.
    """
    parser = argparse.ArgumentParser(description="Stage 3: render a laid-out diagram as a viewable page.")
    parser.add_argument("--process", required=True, help="Process folder name, e.g. 'enrollment'.")
    parser.add_argument(
        "--processes-root",
        type=Path,
        default=DEFAULT_PROCESSES_ROOT,
        help="Directory holding the process folders.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)

    try:
        written = run(args.process, args.processes_root)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        fields = ", ".join(str(item["loc"]) for item in error.errors()[:3])
        print(f"error: the report on disk does not match the schema ({fields})", file=sys.stderr)
        return 2
    except AssetError as error:
        print(f"error: {error}", file=sys.stderr)
        print("nothing written; the page could not be built.", file=sys.stderr)
        return 1

    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
