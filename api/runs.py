"""Runs in flight, and what became of them.

A run takes a minute or two: a model call, then the layouter. Held open as a
single HTTP request it would be dropped long before it finished -- Render cuts a
connection that has gone quiet -- so a run is started, given an id, and polled.
That also means the page can report which stage is running instead of spinning
at nothing.

Deliberately in memory, and deliberately not durable. This backs a demo: a
restart losing what a browser was watching costs one press of Generate, and a
database to avoid that would be the largest thing in the repository.

Runs execute on a single worker, so two of them queue rather than competing for
the same layouter subprocess and the same rate limit.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from bpmn.autolayout import LayoutError
from extractors.errors import ExtractionError, ModelUnavailableError

logger = logging.getLogger(__name__)

QUEUED = "queued"
DONE = "done"
FAILED = "failed"

LABELS = {
    QUEUED: "Waiting for a free worker",
    "extracting": "Reading the description and building the graph",
    "laying_out": "Laying the diagram out",
    "rendering": "Rendering the page",
}
"""What each status says on the page. Written here so the browser only prints it."""


@dataclass(frozen=True)
class Run:
    """One run's state. Frozen: the store swaps whole values rather than mutating."""

    id: str
    status: str = QUEUED
    result: dict[str, object] | None = None
    detail: str | None = None
    started: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def label(self) -> str:
        """A sentence for whoever is waiting."""
        return LABELS.get(self.status, self.status)


class RunStore:
    """Starts runs and remembers them.

    Thread-safe: the worker writes progress while HTTP threads read it, so every
    access goes through one lock.
    """

    def __init__(self, keep: int = 50) -> None:
        """
        Args:
            keep: How many finished runs to remember. Old ones are forgotten
                oldest-first, so a long-lived instance does not grow without
                bound holding diagrams nobody is looking at any more.
        """
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pfg-run")
        self._keep = keep

    def start(self, work: Callable[[Callable[[str], None]], dict[str, object]]) -> Run:
        """Queue a run.

        Args:
            work: The run itself. It is handed a callback to report each stage it
                enters, and returns the payload to hand back.

        Returns:
            The run, queued. It has an id before any work has happened, which is
            what the caller polls with.
        """
        run = Run(id=uuid.uuid4().hex)
        self._put(run)
        self._pool.submit(self._execute, run.id, work)
        return run

    def get(self, run_id: str) -> Run | None:
        """The run with this id, or None if there never was one or it has been forgotten."""
        with self._lock:
            return self._runs.get(run_id)

    def _execute(self, run_id: str, work: Callable[[Callable[[str], None]], dict[str, object]]) -> None:
        def progress(stage: str) -> None:
            self._update(run_id, status=stage)

        try:
            result = work(progress)
        except Exception as error:
            # Whatever went wrong, the browser is entitled to hear about it
            # rather than poll a run that never moves again. This is the worker
            # thread: there is nobody above it to catch anything it lets past.
            logger.exception("run %s failed", run_id)
            self._update(run_id, status=FAILED, detail=_explain(error))
            return
        self._update(run_id, status=DONE, result=result)

    def _update(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, object] | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is not None:
                self._runs[run_id] = replace(current, status=status, result=result, detail=detail)

    def _put(self, run: Run) -> None:
        with self._lock:
            self._runs[run.id] = run
            while len(self._runs) > self._keep:
                self._runs.pop(next(iter(self._runs)))


def _explain(error: Exception) -> str:
    """What to tell whoever is waiting.

    The pipeline's own errors already read as sentences -- an extraction failure
    names what the graph got wrong -- so they are passed through. Anything else
    is a bug here, and says so rather than leaking a traceback into a browser.
    """
    if isinstance(error, ExtractionError):
        return f"{error}\n\n{error.reason()}"
    if isinstance(error, ModelUnavailableError | LayoutError | ValueError):
        return str(error)
    return "Something went wrong inside the pipeline. The service log has the details."
