"""Where sessions are kept."""

from pathlib import Path

import pytest

from knowledge.loader import DomainKnowledge
from session.models import Phase
from session.orchestrator import new_session
from session.store import FileSessionStore, SessionNotFound


def test_a_created_session_can_be_loaded_back_unchanged(tmp_path: Path, domain: DomainKnowledge) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    session = new_session("abc123", domain)

    store.create(session)

    assert store.load("abc123") == session
    assert (tmp_path / "sessions" / "abc123" / "session.json").is_file()


def test_saving_replaces_what_was_stored(tmp_path: Path, domain: DomainKnowledge) -> None:
    store = FileSessionStore(tmp_path)
    session = new_session("abc123", domain)
    store.create(session)

    session.phase = Phase.PROBING
    store.save(session)

    assert store.load("abc123").phase is Phase.PROBING


def test_a_save_leaves_no_temporary_file_behind(tmp_path: Path, domain: DomainKnowledge) -> None:
    """The write goes to a temporary file and is renamed, so a reader never sees half a session."""
    store = FileSessionStore(tmp_path)
    store.create(new_session("abc123", domain))

    assert [path.name for path in (tmp_path / "abc123").iterdir()] == ["session.json"]


def test_a_failed_write_leaves_the_stored_session_as_it_was(
    tmp_path: Path, domain: DomainKnowledge, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSessionStore(tmp_path)
    session = new_session("abc123", domain)
    store.create(session)

    def refuse(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("session.store.os.replace", refuse)
    session.phase = Phase.CLOSING
    with pytest.raises(OSError, match="disk full"):
        store.save(session)

    assert store.load("abc123").phase is Phase.DESCRIBING
    assert [path.name for path in (tmp_path / "abc123").iterdir()] == ["session.json"]


def test_creating_a_session_twice_is_refused(tmp_path: Path, domain: DomainKnowledge) -> None:
    store = FileSessionStore(tmp_path)
    store.create(new_session("abc123", domain))

    with pytest.raises(FileExistsError):
        store.create(new_session("abc123", domain))


def test_an_unknown_session_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(SessionNotFound):
        FileSessionStore(tmp_path).load("nosuch")


@pytest.mark.parametrize("session_id", ["../etc", "a/b", "", "a b", "x" * 65, ".."])
def test_an_id_that_could_not_be_a_folder_name_is_never_turned_into_a_path(tmp_path: Path, session_id: str) -> None:
    """Ids arrive from a URL, so one that walks out of the directory must be refused before it is used."""
    store = FileSessionStore(tmp_path)

    with pytest.raises(SessionNotFound):
        store.load(session_id)
    with pytest.raises(ValueError):
        store.path_for_outputs(session_id, "main")


def test_sessions_are_listed_in_sorted_order(tmp_path: Path, domain: DomainKnowledge) -> None:
    store = FileSessionStore(tmp_path / "not-there-yet")
    assert store.list() == ()

    for session_id in ("bbb", "aaa"):
        store.create(new_session(session_id, domain))

    assert store.list() == ("aaa", "bbb")


def test_a_sessions_flows_are_written_beside_it(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path)

    assert store.path_for_outputs("abc123", "off_label_review") == tmp_path / "abc123" / "flows" / "off_label_review"
    with pytest.raises(ValueError):
        store.path_for_outputs("abc123", "../../elsewhere")


# ── seeds ────────────────────────────────────────────────────────────────────


def seeds(tmp_path: Path, domain: DomainKnowledge, *session_ids: str) -> Path:
    """A seeds folder holding these sessions, each with one finished flow file."""
    folder = tmp_path / "seeds"
    shipped = FileSessionStore(folder)
    for session_id in session_ids:
        shipped.create(new_session(session_id, domain))
        outputs = shipped.path_for_outputs(session_id, "main") / "outputs"
        outputs.mkdir(parents=True)
        (outputs / "diagram.html").write_text("<h1>finished</h1>", encoding="utf-8")
    return folder


def test_seeds_are_restored_into_an_empty_store_with_their_flows(tmp_path: Path, domain: DomainKnowledge) -> None:
    """A host that loses its disk starts every boot with nothing; this is what puts them back."""
    store = FileSessionStore(tmp_path / "sessions")

    restored = store.restore_seeds(seeds(tmp_path, domain, "bbb", "aaa"))

    assert restored == ("aaa", "bbb")
    assert store.list() == ("aaa", "bbb")
    assert (store.path_for_outputs("aaa", "main") / "outputs" / "diagram.html").read_text(
        "utf-8"
    ) == "<h1>finished</h1>"


def test_a_session_already_in_the_store_is_never_overwritten_by_its_seed(
    tmp_path: Path, domain: DomainKnowledge
) -> None:
    """Once restored, a session belongs to whoever carries it on."""
    store = FileSessionStore(tmp_path / "sessions")
    carried_on = new_session("aaa", domain)
    carried_on.phase = Phase.CLOSING
    store.create(carried_on)

    restored = store.restore_seeds(seeds(tmp_path, domain, "aaa", "bbb"))

    assert restored == ("bbb",)
    assert store.load("aaa").phase is Phase.CLOSING


def test_restoring_twice_restores_nothing_the_second_time(tmp_path: Path, domain: DomainKnowledge) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    folder = seeds(tmp_path, domain, "aaa")

    assert store.restore_seeds(folder) == ("aaa",)
    assert store.restore_seeds(folder) == ()


def test_a_missing_seeds_folder_restores_nothing(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path / "sessions")

    assert store.restore_seeds(tmp_path / "no-seeds-here") == ()
    assert store.list() == ()


def test_a_folder_that_could_not_be_a_session_is_not_restored(tmp_path: Path, domain: DomainKnowledge) -> None:
    folder = seeds(tmp_path, domain, "aaa")
    (folder / "not a session id").mkdir()
    (folder / "not a session id" / "session.json").write_text("{}", encoding="utf-8")
    (folder / "notes").mkdir()

    assert FileSessionStore(tmp_path / "sessions").restore_seeds(folder) == ("aaa",)
