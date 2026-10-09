"""How the Anthropic client is configured. No client is built and nothing is sent."""

from pathlib import Path

import pytest

from extractors.model import WORKSPACE_HEADER, _client_args
from utils.settings import load_settings


@pytest.fixture(autouse=True)
def only_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key from the environment and nothing else: no ``.env`` from the machine running the suite."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)


def test_the_key_is_all_that_is_sent_when_no_workspace_is_named() -> None:
    assert _client_args(load_settings()) == {"api_key": "sk-test"}


def test_a_named_workspace_travels_as_a_header_on_every_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key not scoped to a workspace is refused unless each request says which one to use."""
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_123")

    args = _client_args(load_settings())

    assert args == {"api_key": "sk-test", "default_headers": {WORKSPACE_HEADER: "wrkspc_123"}}
