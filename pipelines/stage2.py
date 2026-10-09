"""Stage 2 orchestrator: a validated graph on disk -> a BPMN diagram on disk.

One run: read ``processes/<name>/outputs/graph.json`` -> write semantic BPMN ->
lay it out -> write ``processes/<name>/outputs/diagram.bpmn``. Deterministic. No
model, no network, no credentials; the only thing outside Python is the pinned
`bpmn-auto-layout` CLI, which owns every coordinate in the result.

Close-out only writes a graph that passed the structural tier, so this stage
assumes a well-formed graph rather than re-validating one. It does not
check lane names against ``metadata.yaml`` either: a lane the config never
declared is drawn after the declared ones and logged, since refusing a whole
diagram over a name the source used helps nobody.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from bpmn import colors, decisions, document, semantics
from bpmn.autolayout import Layouter, LayoutError, subprocess_layouter
from ir.models import ProcessGraph
from ir.process_config import GRAPH_FILENAME, OUTPUTS_DIRNAME, SKELETON_FILENAME, load_process_config
from ir.skeleton import load_skeleton
from utils.logs import configure_logging
from utils.settings import load_stage2_settings

logger = logging.getLogger(__name__)

DEFAULT_PROCESSES_ROOT = Path(__file__).resolve().parent.parent / "processes"
DIAGRAM_FILENAME = "diagram.bpmn"


def run(
    process_name: str,
    processes_root: Path = DEFAULT_PROCESSES_ROOT,
    *,
    layout: Layouter | None = None,
) -> Path:
    """Run stage 2 for one process.

    Args:
        process_name: The folder name under ``processes/``.
        processes_root: Where the process folders live.
        layout: The layouter. Defaults to the pinned CLI; injecting one lets the
            orchestration be exercised without Node installed.

    Returns:
        The path written.

    Raises:
        FileNotFoundError: If the process folder or stage 1's graph is missing.
        pydantic.ValidationError: If the graph on disk does not match the schema.
        bpmn.autolayout.LayoutError: If the layouter could not be run or refused
            the document. Nothing is written in that case.
    """
    process_dir = processes_root / process_name
    if not process_dir.is_dir():
        raise FileNotFoundError(f"no process directory at {process_dir}")

    graph_path = process_dir / OUTPUTS_DIRNAME / GRAPH_FILENAME
    if not graph_path.is_file():
        raise FileNotFoundError(f"no graph at {graph_path}; stage 2 draws a flow folder that a finished session wrote")

    graph = ProcessGraph.model_validate(json.loads(graph_path.read_text(encoding="utf-8")))
    config = load_process_config(process_dir)
    skeleton = load_skeleton(process_dir / SKELETON_FILENAME)

    if layout is None:
        settings = load_stage2_settings()
        layout = subprocess_layouter([settings.layout_bin] if settings.layout_bin else None)

    definitions = semantics.translate(graph, config, skeleton)
    laid_out = colors.apply(decisions.widen(layout(document.render(definitions))))

    destination = process_dir / OUTPUTS_DIRNAME / DIAGRAM_FILENAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(laid_out, encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Returns:
        0 on success, 1 if the layout failed, 2 if the process could not be read.
    """
    parser = argparse.ArgumentParser(description="Stage 2: lay a validated process graph out as BPMN.")
    parser.add_argument("--process", required=True, help="Process folder name, e.g. 'enrollment'.")
    parser.add_argument(
        "--processes-root",
        type=Path,
        default=DEFAULT_PROCESSES_ROOT,
        help="Directory holding the process folders.",
    )
    args = parser.parse_args(argv)
    configure_logging()

    try:
        written = run(args.process, args.processes_root)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        fields = ", ".join(str(item["loc"]) for item in error.errors()[:3])
        print(f"error: the graph on disk does not match the schema ({fields})", file=sys.stderr)
        return 2
    except ValueError as error:  # After ValidationError, which subclasses it.
        print(f"error: {error}", file=sys.stderr)
        return 2
    except LayoutError as error:
        print(f"error: {error}", file=sys.stderr)
        print("nothing written; the diagram could not be laid out.", file=sys.stderr)
        return 1

    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
