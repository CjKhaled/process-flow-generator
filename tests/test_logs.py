"""The application log and the model trace."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from utils.logs import APP_LOG_FILENAME, TRACE_FILENAME, configure_logging, current_context, record_call, trace_context
from utils.settings import load_log_settings


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Logging pointed at a throwaway directory at DEBUG, and put back afterwards."""
    original = load_log_settings().log_dir
    monkeypatch.setenv("PFG_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("PFG_LOG_LEVEL", "DEBUG")
    yield configure_logging()
    monkeypatch.setenv("PFG_LOG_DIR", str(original))
    monkeypatch.setenv("PFG_LOG_LEVEL", "WARNING")
    configure_logging()


def call(**overrides: object) -> None:
    fields: dict[str, object] = {
        "role": "extractor",
        "model_id": "claude-test",
        "system_prompt": "You maintain a graph.",
        "prompt": "Update the graph.",
        "output_type": "GraphPatch",
        "seconds": 1.2345,
        "response": {"operations": []},
        "usage": {"inputTokens": 900, "outputTokens": 40, "cacheReadInputTokens": 700},
    }
    record_call(**{**fields, **overrides})  # type: ignore[arg-type]


def trace(log_dir: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (log_dir / TRACE_FILENAME).read_text(encoding="utf-8").splitlines()]


def ours() -> list[logging.Handler]:
    return [handler for handler in logging.getLogger().handlers if getattr(handler, "_pfg_handler", False)]


def test_a_model_call_is_traced_in_full(log_dir: Path) -> None:
    """The trace answers "what exactly was sent and what came back", so nothing is summarised."""
    call()

    (entry,) = trace(log_dir)
    assert entry["role"] == "extractor" and entry["model"] == "claude-test"
    assert entry["system_prompt"] == "You maintain a graph."
    assert entry["prompt"] == "Update the graph."
    assert entry["response"] == {"operations": []}
    assert entry["usage"] == {"inputTokens": 900, "outputTokens": 40, "cacheReadInputTokens": 700}
    assert (entry["ok"], entry["error"], entry["seconds"]) == (True, None, 1.234)


def test_a_failed_call_is_traced_with_its_error(log_dir: Path) -> None:
    """The failed call is the one most worth reading back."""
    call(response=None, error="SchemaCallError: operations.0.op: unknown tag")

    (entry,) = trace(log_dir)
    assert (entry["ok"], entry["response"]) == (False, None)
    assert "unknown tag" in str(entry["error"])


def test_a_trace_entry_says_which_session_turn_and_attempt_it_belongs_to(log_dir: Path) -> None:
    with trace_context(session="abc123", turn=4), trace_context(attempt=2):
        call()

    (entry,) = trace(log_dir)
    assert (entry["session"], entry["turn"], entry["attempt"]) == ("abc123", 4, 2)


def test_context_is_restored_on_the_way_out_and_none_leaves_it_alone() -> None:
    with trace_context(session="abc123", turn=1):
        with trace_context(turn=2, role=None):
            assert current_context() == {"session": "abc123", "turn": 2}
        assert current_context() == {"session": "abc123", "turn": 1}
    assert current_context() == {}


def test_the_cached_block_is_sized_not_copied(log_dir: Path) -> None:
    """It is the same tens of kilobytes on every navigator call, and it is in the repository."""
    call(cached_context="x" * 5000)

    (entry,) = trace(log_dir)
    assert entry["cached_context_chars"] == 5000
    assert "x" * 100 not in json.dumps(entry)


def test_the_log_says_what_happened_and_at_debug_carries_the_text(log_dir: Path) -> None:
    with trace_context(session="abc123", turn=4):
        call()
    for handler in ours():
        handler.flush()

    text = (log_dir / APP_LOG_FILENAME).read_text(encoding="utf-8")
    assert "[abc123 t4 extractor] model call ok: extractor -> GraphPatch in 1.2s" in text
    assert "tokens in 900, out 40, cache read 700" in text
    assert "Update the graph." in text


def test_our_loggers_are_verbose_and_everyone_elses_are_not(log_dir: Path) -> None:
    assert logging.getLogger("session.orchestrator").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING


def test_configuring_again_starts_both_files_afresh_and_adds_no_handlers(log_dir: Path) -> None:
    """Overwritten each start: the last run is the one being debugged."""
    call()
    before = len(ours())

    configure_logging()

    assert len(ours()) == before == 2
    assert (log_dir / TRACE_FILENAME).read_text(encoding="utf-8") == ""
    assert "model call ok" not in (log_dir / APP_LOG_FILENAME).read_text(encoding="utf-8")
