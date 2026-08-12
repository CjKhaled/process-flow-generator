"""Stage 1 orchestrator: source text -> validated graph on disk.

One run: read ``processes/<name>/inputs/`` -> extract -> validate -> write
``processes/<name>/outputs/``. The :class:`~ir.models.ProcessGraph` is held in
memory as the source of truth; the files are its serialisation.

A graph that fails the structural tier is never written. Later stages read
``outputs/`` and are entitled to assume anything they find there is well formed.
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from extractors.errors import ExtractionError
from extractors.model import build_model_call
from extractors.process import DEFAULT_MAX_ATTEMPTS, ExtractionResult, ModelCall, extract
from ir.process_config import INPUTS_DIRNAME, OUTPUTS_DIRNAME, SKELETON_FILENAME, load_process_config
from ir.skeleton import load_skeleton
from utils.io import read_source, write_json
from utils.settings import load_settings

DEFAULT_PROCESSES_ROOT = Path(__file__).resolve().parent.parent / "processes"
GRAPH_FILENAME = "graph.json"
REPORT_FILENAME = "validation.json"


def run(
    process_name: str,
    processes_root: Path = DEFAULT_PROCESSES_ROOT,
    *,
    call: ModelCall | None = None,
    max_attempts: int | None = None,
) -> ExtractionResult:
    """Run stage 1 for one process.

    Args:
        process_name: The folder name under ``processes/``.
        processes_root: Where the process folders live.
        call: The model. Defaults to a Strands agent built from the environment;
            injecting one lets the orchestration be exercised without a network.
        max_attempts: Overrides the configured attempt budget.

    Returns:
        The extracted graph and its validation report.

    Raises:
        FileNotFoundError: If the process folder or its inputs are missing.
        pydantic.ValidationError: If required settings are missing.
        ExtractionError: If no attempt produced a structurally valid graph. Nothing
            is written in that case.
    """
    process_dir = processes_root / process_name
    if not process_dir.is_dir():
        raise FileNotFoundError(f"no process directory at {process_dir}")

    config = load_process_config(process_dir)
    skeleton = load_skeleton(process_dir / SKELETON_FILENAME)
    source_text = read_source(process_dir / INPUTS_DIRNAME)

    if call is None:
        settings = load_settings()
        call = build_model_call(settings, config, skeleton)
        max_attempts = max_attempts or settings.max_extraction_attempts

    result = extract(
        source_text,
        skeleton,
        call=call,
        max_attempts=max_attempts or DEFAULT_MAX_ATTEMPTS,
    )

    outputs = process_dir / OUTPUTS_DIRNAME
    write_json(outputs / GRAPH_FILENAME, result.graph)
    write_json(outputs / REPORT_FILENAME, result.report)
    return result


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

    Returns:
        0 on success, 1 if extraction failed, 2 if the process could not be read.
    """
    parser = argparse.ArgumentParser(description="Stage 1: extract a validated process graph from source text.")
    parser.add_argument("--process", required=True, help="Process folder name, e.g. 'enrollment'.")
    parser.add_argument(
        "--processes-root",
        type=Path,
        default=DEFAULT_PROCESSES_ROOT,
        help="Directory holding the process folders.",
    )
    args = parser.parse_args(argv)

    try:
        result = run(args.process, args.processes_root)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        missing = ", ".join(str(item["loc"][0]) for item in error.errors())
        print(f"error: configuration is incomplete ({missing})", file=sys.stderr)
        print("set ANTHROPIC_API_KEY in the environment or in a .env file.", file=sys.stderr)
        return 2
    except ExtractionError as error:
        print(f"error: {error}", file=sys.stderr)
        if error.report is not None:
            print(error.report.summary(), file=sys.stderr)
        print("nothing written; the graph did not pass the structural tier.", file=sys.stderr)
        return 1

    outputs = args.processes_root / args.process / OUTPUTS_DIRNAME
    print(
        f"extracted {len(result.graph.nodes)} nodes and {len(result.graph.edges)} edges in {result.attempts} attempt(s)"
    )
    print(f"wrote {outputs / GRAPH_FILENAME}")
    print(f"wrote {outputs / REPORT_FILENAME}")

    if result.report.resolution:
        print(f"\n{len(result.report.resolution)} open question(s) for a human:")
        for finding in result.report.resolution:
            print(f"  - {finding.code}: {finding.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
