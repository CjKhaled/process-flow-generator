"""What the application says about itself: the console, ``app.log``, and the model trace.

Two outputs, for two questions.

* **The log** -- console and ``logs/app.log`` -- answers *what happened, when and
  why*. One line per decision: what the interpreter read, which topics moved and
  what moved them, why the extractor was or was not called, which questions were
  kept and which dropped. At ``DEBUG`` it also carries every prompt and response
  in full.
* **The trace** -- ``logs/trace.jsonl`` -- answers *what exactly was sent and
  what came back*. One JSON object per model call, complete: system prompt,
  prompt, response or error, model, duration, token usage. It is written at the
  one place the project talks to a model, so nothing can call a model untraced.

Both files are **overwritten each time the process starts**. This is a debugging
aid, not an audit record: the last run is the one being looked at, and a file
that grows for ever is one nobody reads. Both hold whatever users typed, so
``logs/`` is gitignored for the same reason ``sessions/`` is.

Context -- which session, which turn, which agent, which attempt -- travels in a
context variable set by :func:`trace_context`, so a line deep inside a validator
says whose turn it belongs to without that id being threaded through every
signature on the way down. Turns run on worker threads; a context variable set
inside a worker is that worker's alone.

Logging is configured by entry points, never at import: importing a module of
this project must not open files or change what the caller's loggers do.
"""

import json
import logging
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from utils.settings import load_log_settings

APP_LOG_FILENAME = "app.log"
TRACE_FILENAME = "trace.jsonl"

PACKAGES = (
    "agents",
    "api",
    "bpmn",
    "extractors",
    "ir",
    "knowledge",
    "pipelines",
    "render",
    "session",
    "utils",
    "validators",
)
"""This project's top-level packages: the loggers whose level ``PFG_LOG_LEVEL`` sets."""

_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s %(context)s%(message)s"
_DATE_FORMAT = "%H:%M:%S"
_OURS = "_pfg_handler"

_context: ContextVar[Mapping[str, object]] = ContextVar("pfg_trace_context", default={})  # noqa: B039  # never mutated
_trace_lock = threading.Lock()
_trace_path: Path | None = None

logger = logging.getLogger(__name__)


@contextmanager
def trace_context(**fields: object) -> Iterator[None]:
    """Say where the work inside this block belongs.

    Args:
        fields: Any of ``session``, ``turn``, ``role``, ``attempt``, ``run``.
            Merged over whatever an enclosing block set, and removed again on
            the way out. A value of None leaves the enclosing value in place.
    """
    merged = {**_context.get(), **{key: value for key, value in fields.items() if value is not None}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, object]:
    """The context in force, as a plain dict."""
    return dict(_context.get())


class _ContextFilter(logging.Filter):
    """Puts the trace context on every record, as a short prefix."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = _context.get()
        parts = [str(context[key]) for key in ("run", "session") if key in context]
        if "turn" in context:
            parts.append(f"t{context['turn']}")
        if "role" in context:
            parts.append(str(context["role"]) + (f"#{context['attempt']}" if "attempt" in context else ""))
        record.context = f"[{' '.join(parts)}] " if parts else ""
        return True


class _Console(logging.StreamHandler):  # type: ignore[type-arg]  # StreamHandler is generic only in stubs
    """Writes to whatever ``sys.stderr`` is *now*.

    A plain ``StreamHandler`` keeps the stream it was built with. Anything that
    swaps ``sys.stderr`` afterwards and later closes its replacement -- a test
    runner capturing output does exactly that -- would leave the handler writing
    to a closed file.
    """

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        """Ignored: the stream is always the current ``sys.stderr``."""


def configure_logging() -> Path:
    """Turn the application's logging on. Call from an entry point, once.

    Safe to call again: the handlers it installed before are replaced, not added
    to, and both files are truncated -- a second call is a fresh start.

    Returns:
        The directory the log and the trace are written to.
    """
    global _trace_path  # noqa: PLW0603  # one process, one trace file
    settings = load_log_settings()
    directory = settings.log_dir
    directory.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in [handler for handler in root.handlers if getattr(handler, _OURS, False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)
    for handler in (_Console(), logging.FileHandler(directory / APP_LOG_FILENAME, mode="w", encoding="utf-8")):
        setattr(handler, _OURS, True)
        handler.setFormatter(formatter)
        handler.addFilter(_ContextFilter())
        root.addHandler(handler)

    # Everything of ours at the configured level; everyone else only when something is wrong.
    root.setLevel(logging.WARNING)
    for package in PACKAGES:
        logging.getLogger(package).setLevel(settings.log_level.upper())

    with _trace_lock:
        _trace_path = directory / TRACE_FILENAME
        _trace_path.write_text("", encoding="utf-8")

    logger.info(
        "logging at %s; log and model trace in %s (overwritten each start)", settings.log_level.upper(), directory
    )
    return directory


def record_call(
    *,
    role: str,
    model_id: str,
    system_prompt: str,
    prompt: str,
    output_type: str,
    seconds: float,
    cached_context: str | None = None,
    response: object | None = None,
    error: str | None = None,
    usage: Mapping[str, Any] | None = None,
) -> None:
    """Record one model call: a line in the trace, a summary on the console.

    Args:
        role: Which agent made the call.
        model_id: The model it went to.
        system_prompt: The agent's instructions, in full.
        prompt: The user turn, in full.
        output_type: The name of the schema the answer had to fit.
        seconds: How long the call took.
        cached_context: The cached block, if the conversation has one.
        response: The parsed answer, as JSON-ready data. None when the call failed.
        error: What went wrong, when it did.
        usage: Token counts as the provider reported them.
    """
    tokens = dict(usage or {})
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        **current_context(),
        "role": role,
        "model": model_id,
        "output_type": output_type,
        "seconds": round(seconds, 3),
        "usage": tokens,
        "ok": error is None,
        "error": error,
        "system_prompt": system_prompt,
        "cached_context_chars": len(cached_context) if cached_context else 0,
        "prompt": prompt,
        "response": response,
    }

    with trace_context(role=role):
        if error is None:
            logger.info(
                "model call ok: %s -> %s in %.1fs | tokens in %s, out %s, cache read %s, cache write %s | model %s",
                role,
                output_type,
                seconds,
                tokens.get("inputTokens", "?"),
                tokens.get("outputTokens", "?"),
                tokens.get("cacheReadInputTokens", 0),
                tokens.get("cacheWriteInputTokens", 0),
                model_id,
            )
        else:
            logger.warning("model call failed: %s -> %s after %.1fs: %s", role, output_type, seconds, error)
        logger.debug("prompt to %s (%d chars):\n%s", role, len(prompt), prompt)
        if response is not None:
            logger.debug("response from %s:\n%s", role, json.dumps(response, indent=2, ensure_ascii=False))

    with _trace_lock:
        if _trace_path is not None:
            with _trace_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
