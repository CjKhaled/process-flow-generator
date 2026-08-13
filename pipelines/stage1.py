"""Stage 1 orchestrator: source text -> validated graph on disk.

One run: read ``processes/<name>/inputs/`` -> extract -> validate -> write
``processes/<name>/outputs/``. The :class:`~ir.models.ProcessGraph` is held in
memory as the source of truth; the files are its serialisation.

A graph that fails the structural tier is never written. Later stages read
``outputs/`` and are entitled to assume anything they find there is well formed.
"""

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from extractors.errors import ExtractionError, ModelUnavailableError
from extractors.model import build_model_call
from extractors.process import DEFAULT_MAX_ATTEMPTS, ExtractionResult, ModelCall, extract
from ir.process_config import (
    INPUTS_DIRNAME,
    METADATA_FILENAME,
    OUTPUTS_DIRNAME,
    SKELETON_FILENAME,
    ProcessConfig,
    load_process_config,
)
from ir.skeleton import Skeleton, load_skeleton
from utils.io import read_source, write_json
from utils.settings import load_settings

logger = logging.getLogger(__name__)

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
        ValueError: If the folder, metadata, and skeleton disagree about the name.
        pydantic.ValidationError: If required settings are missing.
        ExtractionError: If no attempt produced a structurally valid graph. Nothing
            is written in that case.
    """
    process_dir = processes_root / process_name
    if not process_dir.is_dir():
        raise FileNotFoundError(f"no process directory at {process_dir}")

    config = load_process_config(process_dir)
    skeleton = load_skeleton(process_dir / SKELETON_FILENAME)
    _check_names_agree(process_name, config, skeleton)
    source_text = read_source(process_dir / INPUTS_DIRNAME)

    if call is None:
        settings = load_settings()
        call = build_model_call(settings, config, skeleton)
        if max_attempts is None:
            max_attempts = settings.max_extraction_attempts

    result = extract(
        source_text,
        skeleton,
        call=call,
        # `is None` rather than `or`: an explicit 0 must reach the guard in extract().
        max_attempts=DEFAULT_MAX_ATTEMPTS if max_attempts is None else max_attempts,
    )

    if result.graph.process_name != process_name:
        # Not fatal: a mislabelled but otherwise sound graph is worth keeping.
        logger.warning(
            "the model named the graph '%s', but this is the '%s' process",
            result.graph.process_name,
            process_name,
        )

    outputs = process_dir / OUTPUTS_DIRNAME
    write_json(outputs / GRAPH_FILENAME, result.graph)
    write_json(outputs / REPORT_FILENAME, result.report)
    return result


def _check_names_agree(process_name: str, config: ProcessConfig, skeleton: Skeleton) -> None:
    """Fail before spending a model call when the three copies of the name disagree.

    The folder, ``metadata.yaml`` and ``skeleton.json`` each carry the process name
    and nothing else cross-checks them. Adding a process means copying a folder, so
    a half-edited copy would otherwise extract one process's vocabulary under
    another's filename.

    Raises:
        ValueError: If either file names a different process than the folder.
    """
    mismatched = [
        f"{filename} says '{found}'"
        for filename, found in (
            (METADATA_FILENAME, config.process_name),
            (SKELETON_FILENAME, skeleton.process_name),
        )
        if found != process_name
    ]
    if mismatched:
        raise ValueError(f"the process folder is named '{process_name}' but {' and '.join(mismatched)}")


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
    # Our own progress at INFO; the SDK and HTTP client stay quiet unless something breaks.
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    logging.getLogger("extractors").setLevel(logging.INFO)

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
    except ValueError as error:  # After ValidationError, which subclasses it.
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ModelUnavailableError as error:
        print(f"error: {error}", file=sys.stderr)
        print("check PFG_MODEL_ID and the API key; nothing was written.", file=sys.stderr)
        return 2
    except ExtractionError as error:
        print(f"error: {error}", file=sys.stderr)
        print(f"the last of {error.attempts} attempt(s) failed because:", file=sys.stderr)
        print(error.reason(), file=sys.stderr)
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
