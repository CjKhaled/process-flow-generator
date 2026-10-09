"""The sessions that ship with the repository.

They are restored on a host that keeps no disk, so they are the only sessions a
deployed copy is guaranteed to have. They are also plain files written by an
earlier version of the code, which is exactly what goes stale without anyone
noticing -- so each one is read through today's schema and served through today's
endpoints here.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from knowledge.loader import load_domain
from session.closeout import list_outputs
from session.models import Phase
from session.store import SESSION_FILENAME, FileSessionStore
from tests.conftest import DOMAIN_DIR, REPO_ROOT, SEED_SESSIONS_DIR
from tests.fakes import FakeConversations

SEEDS = sorted(path.parent.name for path in SEED_SESSIONS_DIR.glob(f"*/{SESSION_FILENAME}"))


def test_there_are_seed_sessions() -> None:
    assert SEEDS, "the deployed copy would start with nothing to go back to"


@pytest.mark.parametrize("session_id", SEEDS)
def test_a_seed_loads_through_the_current_schema(session_id: str) -> None:
    session = FileSessionStore(SEED_SESSIONS_DIR).load(session_id)

    assert session.id == session_id
    assert session.turn_status == "idle", "a seed caught mid-turn would be restored as interrupted"
    assert session.graph.nodes and session.transcript


@pytest.mark.parametrize("session_id", SEEDS)
def test_a_finished_seed_ships_every_flow_it_lists(session_id: str) -> None:
    store = FileSessionStore(SEED_SESSIONS_DIR)
    session = store.load(session_id)
    if session.phase is not Phase.COMPLETE:
        pytest.skip("not finished, so it has no diagrams to ship")
    domain = load_domain(session.process_id, DOMAIN_DIR)

    listed = list_outputs(session, domain, store)

    assert listed and listed[0]["flow"] == "main"
    assert all(entry["files"] == ["diagram.bpmn", "diagram.html", "graph.json"] for entry in listed)


def test_restored_seeds_are_listed_and_served(tmp_path: Path) -> None:
    """End to end, as a fresh host sees it: an empty disk, then the seeds, then the page asking for them."""
    store = FileSessionStore(tmp_path / "sessions")
    assert store.restore_seeds(SEED_SESSIONS_DIR) == tuple(SEEDS)
    app = create_app(
        conversations=FakeConversations(), session_store=store, domain_dir=DOMAIN_DIR, frontend_dir=tmp_path / "none"
    )

    with TestClient(app) as client:
        listed = client.get("/sessions").json()
        assert {row["id"] for row in listed} == set(SEEDS)
        for row in listed:
            state = client.get(f"/sessions/{row['id']}").json()
            assert state["views"], row["id"]
            assert len(state["outputs"]) == row["flows"]
            for output in state["outputs"]:
                page = client.get(f"/sessions/{row['id']}/flows/{output['flow']}/page")
                assert page.status_code == 200 and "<html" in page.text


def test_seeds_are_committed_and_live_sessions_are_not() -> None:
    """Sharing one folder would commit whatever anyone typed."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").split()

    assert "sessions/" in ignored
    assert "seed_sessions/" not in ignored
