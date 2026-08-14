"""Stage 3 orchestrator: a BPMN file on disk -> a page a human can open.

One run: read ``processes/<name>/outputs/diagram.bpmn`` and, if it is there, the
validation report beside it -> write ``processes/<name>/outputs/diagram.html``.
Deterministic, like stage 2: no model, no network, and nothing read at view time
either, since the viewer is inlined into the page.

The report is optional, and so is the graph beside it. A diagram is renderable
whether or not the questions that came with it are still on disk, and refusing to
draw one because a sibling file was deleted would be a rule with nothing behind
it. Stage 2's output is not optional: without it there is nothing to render, and
the error says which stage to run.

The graph is read for one thing only: stage 2 draws each subprocess as a single
collapsed box, so a question raised on a step inside one has to be pointed at
that box instead. Working out which box means re-deriving stage 2's mapping,
which needs the graph and the skeleton. Without them the page still renders --
every question simply points at its own element, which is correct for a diagram
that collapsed nothing and merely inert for one that did.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from bpmn.semantics import element_ids
from ir.models import ProcessGraph
from ir.process_config import OUTPUTS_DIRNAME, SKELETON_FILENAME, load_process_config
from ir.skeleton import load_skeleton
from pipelines.stage1 import GRAPH_FILENAME, REPORT_FILENAME
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
        pydantic.ValidationError: If the report or graph on disk does not match
            the schema.
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
        _element_map(process_dir),
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


def _element_map(process_dir: Path) -> dict[str, str] | None:
    """Stage 2's IR id -> BPMN id mapping, re-derived, or nothing if it cannot be.

    Re-derived rather than stored: it is a pure function of the graph and the
    skeleton, both of which are already on disk, and a fourth output file would
    be one more thing to keep in step with the three that matter.
    """
    graph_path = process_dir / OUTPUTS_DIRNAME / GRAPH_FILENAME
    skeleton_path = process_dir / SKELETON_FILENAME
    if not graph_path.is_file() or not skeleton_path.is_file():
        logger.warning(
            "no graph at %s or skeleton at %s; questions raised inside a collapsed subprocess will not be clickable",
            graph_path,
            skeleton_path,
        )
        return None
    graph = ProcessGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
    return element_ids(graph, load_skeleton(skeleton_path))


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
