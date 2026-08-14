"""One run of stages 1-3, from posted text, entirely in memory.

The web equivalent of running the three orchestrators in a row -- with the file
system left out of it. A hosted run belongs to whoever typed the text, not to
the repository, so nothing here writes to ``processes/<name>/outputs/``: the
result is a payload returned over HTTP and then forgotten.

Everything it does is composed from the same functions the CLI stages call.
There is no second copy of a stage here, and there must never be one: the demo
exists to show what the pipeline does, so the moment it does something slightly
different it stops being a demo of anything.

Only the process *configuration* is read from disk -- ``metadata.yaml`` and
``skeleton.json``, which ship with the repository and describe the process, not
the run.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from bpmn import decisions, document, semantics
from bpmn.autolayout import Layouter, subprocess_layouter
from extractors.model import build_model_call
from extractors.process import DEFAULT_MAX_ATTEMPTS, ModelCall, extract
from ir.process_config import SKELETON_FILENAME, load_process_config
from ir.skeleton import load_skeleton
from render import page
from utils.settings import load_settings, load_stage2_settings

logger = logging.getLogger(__name__)

DEFAULT_PROCESSES_ROOT = Path(__file__).resolve().parent.parent / "processes"

Progress = Callable[[str], None]
"""Called with a stage name as the run enters it, so a caller can report it."""

EXTRACTING = "extracting"
LAYING_OUT = "laying_out"
RENDERING = "rendering"


def run(
    process_name: str,
    source_text: str,
    processes_root: Path = DEFAULT_PROCESSES_ROOT,
    *,
    call: ModelCall | None = None,
    layout: Layouter | None = None,
    progress: Progress | None = None,
) -> dict[str, object]:
    """Extract, validate, lay out and render one process description.

    Args:
        process_name: The folder name under ``processes/``.
        source_text: The description that was typed in.
        processes_root: Where the process folders live.
        call: The model. Defaults to a Strands agent built from the environment;
            injecting one lets this be exercised without a network.
        layout: The layouter. Defaults to the pinned CLI; injecting one lets this
            be exercised without Node.
        progress: Notified as each stage begins.

    Returns:
        The payload :mod:`render.page` builds -- the same object stage 3 inlines
        into ``diagram.html``, so the hosted page and the offline one show the
        same result.

    Raises:
        FileNotFoundError: If there is no such process.
        pydantic.ValidationError: If required settings are missing.
        extractors.errors.ExtractionError: If no attempt produced a structurally
            valid graph.
        extractors.errors.ModelUnavailableError: If the API rejected the request.
        ValueError: If a node names an actor ``metadata.yaml`` does not declare.
        bpmn.autolayout.LayoutError: If the diagram could not be laid out.
    """
    process_dir = processes_root / process_name
    if not process_dir.is_dir():
        raise FileNotFoundError(f"there is no '{process_name}' process")

    # Said before the setup rather than after it: building the agent is a second
    # or two of Strands start-up, and "waiting for a free worker" is a poor
    # description of it for whoever is watching the page.
    _say(progress, EXTRACTING)

    config = load_process_config(process_dir)
    skeleton = load_skeleton(process_dir / SKELETON_FILENAME)
    max_attempts = DEFAULT_MAX_ATTEMPTS

    if call is None:
        settings = load_settings()
        call = build_model_call(settings, config, skeleton)
        max_attempts = settings.max_extraction_attempts
    if layout is None:
        layout_bin = load_stage2_settings().layout_bin
        layout = subprocess_layouter([layout_bin] if layout_bin else None)

    result = extract(source_text, skeleton, call=call, max_attempts=max_attempts)

    _say(progress, LAYING_OUT)
    definitions = semantics.translate(result.graph, config, skeleton)
    laid_out = decisions.widen(layout(document.render(definitions)))

    _say(progress, RENDERING)
    return page.payload(
        laid_out,
        result.report.resolution,
        config.display_name,
        semantics.element_ids(result.graph, skeleton),
    )


def _say(progress: Progress | None, stage: str) -> None:
    if progress is not None:
        progress(stage)
