"""The layouter boundary: semantic BPMN in, BPMN with diagram interchange out.

Stage 2 computes no geometry. It hands `bpmn-io/bpmn-auto-layout` a document
with no DI and gets back one with shape bounds, edge waypoints and label bounds
for every element. That library is a BPMN-specific layered layouter rather than
a general graph one, which is the reason it is here: it knows that a lane
constrains a node, that a gateway's branches are a narrative, and that an edge
must not cross a shape it has nothing to do with.

The version is pinned exactly, and to a **pre-release**, in ``js/``. This is
deliberate and not an oversight: the stable line, 1.3.0, has no lane support at
all -- its layouter is twelve files with no notion of a lane -- and lanes are the
whole point of this stage. 2.x is the rewrite that added them. The pin is exact
because an alpha may change under a caret, and the integration test is what
notices if a later version regresses.

It is invoked as a subprocess rather than through a wrapper script because its
CLI already reads XML on stdin and writes it on stdout, so a wrapper would only
add a file to maintain. That leaves the project with a Node dependency and no
JavaScript of its own.
"""

import json
import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

LAYOUTER = Path(__file__).resolve().parent.parent / "js" / "node_modules" / ".bin" / "bpmn-auto-layout"

STDIN_ARGUMENT = "-"
"""What the CLI calls the input path when it should read standard input."""


class LayoutError(RuntimeError):
    """The layouter could not be run, or refused the document."""


class Layouter(Protocol):
    """Lays a semantic BPMN document out. The seam that keeps Node out of most of the suite."""

    def __call__(self, xml: str) -> str:
        """Add diagram interchange to a document.

        Args:
            xml: Semantic BPMN, with or without existing DI.

        Returns:
            The same document with complete DI.
        """
        ...


def subprocess_layouter(command: Sequence[str] | None = None) -> Layouter:
    """Build a layouter that shells out to the pinned CLI.

    Args:
        command: The executable and any leading arguments. Defaults to the
            vendored install.

    Returns:
        A callable satisfying :class:`Layouter`.
    """
    argv = list(command or [str(LAYOUTER)])

    def layout(xml: str) -> str:
        try:
            completed = subprocess.run(  # noqa: S603  # pinned local executable, no shell
                [*argv, STDIN_ARGUMENT],
                input=xml,
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, PermissionError) as error:
            raise LayoutError(
                f"could not run '{argv[0]}'; stage 2 needs Node and `npm ci --prefix {LAYOUTER.parents[2]}`"
            ) from error

        if completed.returncode != 0:
            raise LayoutError(f"the layouter rejected the diagram: {completed.stderr.strip() or 'no diagnostic'}")
        if not completed.stdout.strip():
            raise LayoutError("the layouter returned an empty document")

        _log_warnings(completed.stderr)
        return completed.stdout

    return layout


def _log_warnings(stderr: str) -> None:
    """Surface the layouter's warnings without failing on them.

    On a successful run stderr carries JSON lines, one per warning. A warning
    means an element was not drawn -- worth seeing, but it is the layouter's
    judgement about a diagram it accepted, not a defect in what we sent, so it
    is reported rather than raised.
    """
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            warning = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("layouter: %s", line)
            continue
        logger.warning(
            "layouter: %s %s",
            warning.get("code", "warning"),
            warning.get("message") or warning.get("elementId") or "",
        )
