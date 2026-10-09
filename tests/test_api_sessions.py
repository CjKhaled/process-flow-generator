"""The conversation's HTTP surface, with every outside dependency injected.

The agents, the layouter and the viewer's files are constructor arguments, so a
session here runs the real pipeline, the real store and the real close-out with
no key, no network and no Node. A turn runs on a worker thread and is polled, so
every test that starts one waits for it; :func:`settled` is that wait, with a
timeout, so a stuck turn fails the suite instead of hanging it.
"""

import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents.interpreter import InterpretedStatement, InterpretResult, TopicReading
from agents.navigator import NavigatorQuestion, NavigatorResult
from api.app import create_app
from api.sessions import BUSY, INTERRUPTED, QUICK_REPLIES, UNCONFIGURED
from bpmn.document import BPMN_NS
from extractors.conversation import EXTRACTOR, INTERPRETER
from extractors.errors import ModelUnavailableError, SchemaCallError
from render.assets import ViewerAssets
from session.models import TurnStatus
from session.orchestrator import NOT_UPDATED, RESEND
from session.store import FileSessionStore
from tests.conftest import DOMAIN_DIR, DOMAIN_PROCESS, echo_layouter
from tests.fakes import FakeConversations
from tests.session_builders import DESCRIPTION, first_patch, patch
from tests.test_session_loop import FIRST_READING

TIMEOUT_S = 10.0


def says(text: str = "Got it.", *candidate_ids: str) -> NavigatorResult:
    questions = tuple(NavigatorQuestion(candidate_id=c, kind="gap", text="What happens then?") for c in candidate_ids)
    return NavigatorResult(focus="main", questions=questions, reply=text)


def reads(text: str, *topics: tuple[str, str]) -> InterpretResult:
    return InterpretResult(
        statements=(InterpretedStatement(index=1, raw_text=text),),
        topic_updates=tuple(TopicReading(topic_id=t, status=s, statement_refs=(1,)) for t, s in topics),  # type: ignore[arg-type]
    )


@pytest.fixture
def fake() -> FakeConversations:
    """Scripted for a first turn; tests queue whatever comes after."""
    return FakeConversations().interpreter(FIRST_READING).extractor(first_patch()).navigator(says("Got it.", "c1"))


@pytest.fixture
def store(tmp_path: Path) -> FileSessionStore:
    return FileSessionStore(tmp_path / "sessions")


@pytest.fixture
def client(
    fake: FakeConversations, store: FileSessionStore, tmp_path: Path, viewer_assets: ViewerAssets
) -> Iterator[TestClient]:
    app = create_app(
        conversations=fake,
        session_store=store,
        layout=echo_layouter,
        assets=viewer_assets,
        domain_dir=DOMAIN_DIR,
        frontend_dir=tmp_path / "no-frontend",
    )
    with TestClient(app) as running:
        yield running


def settled(client: TestClient, session_id: str) -> dict[str, Any]:
    """Poll until no turn is running, as the page does.

    Raises:
        AssertionError: If one is still running at the timeout.
    """
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        state = client.get(f"/sessions/{session_id}").json()
        if not state["running"]:
            return dict(state)
        time.sleep(0.02)
    raise AssertionError(f"session {session_id} still had a turn running after {TIMEOUT_S}s")


def begin(client: TestClient, description: str = DESCRIPTION) -> str:
    response = client.post("/sessions", json={"process_id": DOMAIN_PROCESS, "description": description})
    assert response.status_code == 202, response.text
    return str(response.json()["session_id"])


def started(client: TestClient) -> dict[str, Any]:
    return settled(client, begin(client))


def send(client: TestClient, session_id: str, **body: object) -> dict[str, Any]:
    response = client.post(f"/sessions/{session_id}/messages", json=body)
    assert response.status_code == 202, response.text
    return settled(client, session_id)


# ── starting ─────────────────────────────────────────────────────────────────


def test_the_processes_a_conversation_can_be_about_are_listed(client: TestClient) -> None:
    assert client.get("/processes").json() == [{"id": DOMAIN_PROCESS, "display_name": "Intake & Enrollment"}]


def test_health_answers_without_touching_anything(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_the_one_shot_endpoints_are_gone(client: TestClient) -> None:
    """There is one way in now. A client still posting a run should be told so, not left waiting."""
    assert client.post("/runs", json={"process": "enrollment", "source": "x"}).status_code == 404
    assert client.get("/runs/anything").status_code == 404


def test_starting_a_session_answers_at_once_and_the_first_turn_arrives_by_polling(client: TestClient) -> None:
    state = started(client)

    assert (state["turn"], state["phase"], state["turn_status"]) == (1, "probing", "idle")
    assert state["process_name"] == "Intake & Enrollment"
    assert [message["role"] for message in state["transcript"]] == ["user", "assistant"]
    assert state["transcript"][1]["text"] == "Got it."
    assert [question["text"] for question in state["pending"]] == ["What happens then?"]


def test_the_state_carries_the_live_view_and_the_rationale_behind_each_step(client: TestClient) -> None:
    state = started(client)
    main = state["views"][0]

    assert (main["id"], main["label"]) == ("main", "Main flow")
    assert [node["id"] for node in main["nodes"]] == [
        "start",
        "key_form",
        "gw_complete",
        "end_enrolled",
        "end_incomplete",
    ]
    assert main["rationale"]["key_form"]["evidence"][0]["quote"] == "The vendor keys the form"
    assert main["rationale"]["end_incomplete"]["open_question"].startswith("What happens when the form is not complete")
    assert {"source": "gw_complete", "target": "end_enrolled", "label": "the form is complete"}.items() <= main[
        "edges"
    ][2].items()


def test_the_state_carries_lanes_coverage_and_what_is_open(client: TestClient) -> None:
    state = started(client)

    assert [(lane["name"], lane["persona"], lane["default"]) for lane in state["lanes"]] == [
        ("HCP", "HCP office", False),
        ("Vendor", "External hub vendor", False),
        ("CRM", "CRM and automation", True),
    ]
    main = state["coverage"][0]
    assert (main["scope"], main["label"]) == ("main", "Main flow")
    assert main["counts"]["present"] == 2
    assert {"id": "consent.types", "title": "Consent types"}.items() <= next(
        topic for topic in main["open_topics"] if topic["id"] == "consent.types"
    ).items()
    assert "node:end_incomplete" in {item["key"] for item in state["open_items"]}
    assert state["focus_label"] == "Main flow"


def test_what_the_page_says_is_worded_by_the_service(client: TestClient) -> None:
    state = started(client)

    assert state["quick_replies"] == [
        {"id": "not_sure", "label": "Not sure yet"},
        {"id": "not_applicable", "label": "Not part of our process"},
    ]
    assert state["status_label"] == ""


def test_an_empty_description_is_refused(client: TestClient) -> None:
    assert client.post("/sessions", json={"process_id": DOMAIN_PROCESS, "description": "  "}).status_code == 422


def test_an_oversized_description_is_refused(client: TestClient) -> None:
    response = client.post("/sessions", json={"process_id": DOMAIN_PROCESS, "description": "x" * 20_001})

    assert response.status_code == 413
    assert "20,000" in response.json()["detail"]


def test_an_unknown_process_is_refused_before_anything_is_stored(client: TestClient, store: FileSessionStore) -> None:
    response = client.post("/sessions", json={"process_id": "onboarding", "description": DESCRIPTION})

    assert response.status_code == 404
    assert store.list() == ()


def test_an_unknown_session_is_not_found(client: TestClient) -> None:
    assert client.get("/sessions/nosuchsession").status_code == 404
    assert client.post("/sessions/nosuchsession/messages", json={"text": "hi"}).status_code == 404
    assert client.get("/sessions/..%2F..%2Fetc").status_code == 404


# ── answering ────────────────────────────────────────────────────────────────


def test_an_answer_runs_a_turn_and_the_new_reply_arrives_by_polling(
    client: TestClient, fake: FakeConversations
) -> None:
    session_id = started(client)["id"]
    fake.interpreter(reads("We collect HIPAA consent.", ("consent.types", "present")))
    fake.extractor(patch()).navigator(says("Noted the consent."))

    state = send(client, session_id, text="We collect HIPAA consent.")

    assert state["turn"] == 2
    assert state["transcript"][-1]["text"] == "Noted the consent."
    assert state["transcript"][-2] == {"role": "user", "text": "We collect HIPAA consent.", "turn": 2, "questions": []}
    assert state["coverage"][0]["counts"]["present"] == 3


def test_a_quick_reply_is_sent_as_words_with_what_it_means(client: TestClient, fake: FakeConversations) -> None:
    """So the transcript reads naturally and the interpreter treats a button and typed words alike."""
    session_id = started(client)["id"]
    fake.interpreter(reads("Not sure yet", ("consent.types", "deferred"))).navigator(says())

    state = send(client, session_id, quick_reply="not_sure", question_id="q_0001")

    assert state["transcript"][-2]["text"] == "Not sure yet"
    assert QUICK_REPLIES["not_sure"][1] in fake.prompts[INTERPRETER][-1]
    assert "The user chose to answer question q_0001." in fake.prompts[INTERPRETER][-1]
    assert fake.calls(EXTRACTOR) == 1


def test_an_empty_answer_and_an_unknown_quick_reply_are_refused(client: TestClient) -> None:
    session_id = started(client)["id"]

    assert client.post(f"/sessions/{session_id}/messages", json={"text": "  "}).status_code == 422
    assert client.post(f"/sessions/{session_id}/messages", json={"quick_reply": "maybe"}).status_code == 422


def test_a_second_message_while_a_turn_is_running_is_refused(
    store: FileSessionStore, tmp_path: Path, viewer_assets: ViewerAssets
) -> None:
    """One session never runs two turns: the second would start from a state the first is replacing."""

    class Slow(FakeConversations):
        def open(self, role: str, system_prompt: str, cached_context: str | None = None):  # type: ignore[no-untyped-def]
            time.sleep(0.15)
            return super().open(role, system_prompt, cached_context)

    fake = Slow().interpreter(FIRST_READING).extractor(first_patch()).navigator(says())
    app = create_app(
        conversations=fake,
        session_store=store,
        layout=echo_layouter,
        assets=viewer_assets,
        domain_dir=DOMAIN_DIR,
        frontend_dir=tmp_path / "f",
    )
    with TestClient(app) as client:
        session_id = begin(client)
        during = client.get(f"/sessions/{session_id}").json()
        refused = client.post(f"/sessions/{session_id}/messages", json={"text": "too soon"})

        assert during["running"] and during["turn_status"] in {"queued", "interpreting", "extracting", "navigating"}
        assert during["status_label"].endswith("…")
        assert (refused.status_code, refused.json()["detail"]) == (409, BUSY)
        assert settled(client, session_id)["turn"] == 1


def test_a_rejected_turn_says_why_and_changes_nothing(client: TestClient, fake: FakeConversations) -> None:
    before = started(client)
    fake.interpreter(SchemaCallError("bad"), SchemaCallError("worse"))

    after = send(client, before["id"], text="An answer.")

    assert (after["turn_status"], after["status_label"]) == ("failed", RESEND)
    assert (after["turn"], after["transcript"], after["views"]) == (
        before["turn"],
        before["transcript"],
        before["views"],
    )


def test_a_refused_request_is_reported_and_the_user_can_retry(client: TestClient, fake: FakeConversations) -> None:
    session_id = started(client)["id"]
    fake.interpreter(ModelUnavailableError("the API rejected the request: invalid x-api-key"))

    failed = send(client, session_id, text="An answer.")
    assert "invalid x-api-key" in failed["status_label"]

    fake.interpreter(reads("An answer.")).extractor(patch()).navigator(says("Second try."))
    retried = send(client, session_id, text="An answer.")

    assert (retried["turn"], retried["turn_status"]) == (2, "idle")
    assert retried["transcript"][-1]["text"] == "Second try."


def test_when_the_flow_could_not_be_updated_the_page_is_told(client: TestClient, fake: FakeConversations) -> None:
    session_id = started(client)["id"]
    broken = patch(*first_patch().operations[:1])
    fake.interpreter(reads("The vendor archives it.")).extractor(broken, broken, broken).navigator(says())

    state = send(client, session_id, text="The vendor archives it.")

    assert state["flow_updated"] is False
    assert state["notice"] == NOT_UPDATED
    assert len(state["views"][0]["nodes"]) == 5, "the previous graph is still what is shown"


def test_a_session_left_mid_turn_by_a_restart_is_reported_as_interrupted(
    client: TestClient, store: FileSessionStore, fake: FakeConversations
) -> None:
    """No worker holds the turn, so nothing will ever finish it. The page must be told, not left polling."""
    session_id = started(client)["id"]
    session = store.load(session_id)
    session.turn_status = TurnStatus.EXTRACTING
    store.save(session)

    state = client.get(f"/sessions/{session_id}").json()

    assert (state["running"], state["turn_status"], state["status_label"]) == (False, "failed", INTERRUPTED)

    fake.interpreter(reads("again")).extractor(patch()).navigator(says("Carrying on."))

    assert send(client, session_id, text="again")["transcript"][-1]["text"] == "Carrying on."


def test_a_service_with_no_key_starts_and_explains_itself_on_the_first_turn(
    store: FileSessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # away from the repository's .env
    app = create_app(
        session_store=store,
        domain_dir=DOMAIN_DIR,
        frontend_dir=tmp_path / "f",
    )
    with TestClient(app) as client:
        state = settled(client, begin(client))

    assert state["turn_status"] == "failed"
    assert state["status_label"] == f"{UNCONFIGURED} (ANTHROPIC_API_KEY)"


# ── focus ────────────────────────────────────────────────────────────────────


def test_opening_a_flow_is_recorded_and_honoured_on_the_next_turn(client: TestClient, fake: FakeConversations) -> None:
    session_id = started(client)["id"]

    assert client.post(f"/sessions/{session_id}/focus", json={"focus": "off_label_review"}).json() == {
        "focus": "off_label_review"
    }
    assert client.get(f"/sessions/{session_id}").json()["requested_focus"] == "off_label_review"

    fake.interpreter(reads("Ok.")).extractor(patch()).navigator(says())
    state = send(client, session_id, text="Ok.")

    assert (state["focus"], state["focus_label"], state["requested_focus"]) == (
        "off_label_review",
        "Off-label review",
        None,
    )


def test_a_flow_that_does_not_exist_cannot_be_opened(client: TestClient) -> None:
    session_id = started(client)["id"]

    assert client.post(f"/sessions/{session_id}/focus", json={"focus": "onboarding"}).status_code == 422


# ── finishing ────────────────────────────────────────────────────────────────


def test_closing_lists_what_is_open_and_stops_asking(client: TestClient, fake: FakeConversations) -> None:
    session_id = started(client)["id"]
    fake.navigator(says("Here is what is still open."))

    assert client.post(f"/sessions/{session_id}/close").status_code == 202
    state = settled(client, session_id)

    assert state["phase"] == "closing"
    assert state["pending"] == []
    assert state["transcript"][-1]["text"] == "Here is what is still open."
    assert {"key": "node:end_incomplete", "scope": "main", "scope_label": "Main flow", "kind": "step"}.items() <= next(
        item for item in state["open_items"] if item["key"] == "node:end_incomplete"
    ).items()


def test_answering_an_open_item_returns_to_the_conversation(client: TestClient, fake: FakeConversations) -> None:
    session_id = started(client)["id"]
    fake.navigator(says("Open items."))
    client.post(f"/sessions/{session_id}/close")
    settled(client, session_id)
    fake.interpreter(reads("It goes back to the office.")).extractor(patch()).navigator(says("Thanks."))

    state = send(client, session_id, text="It goes back to the office.", item_key="node:end_incomplete")

    assert state["phase"] == "probing"
    assert "steps: End Incomplete (end_incomplete)" in fake.prompts[INTERPRETER][-1]


def test_accepting_produces_downloadable_bpmn_and_html_for_the_flow(client: TestClient) -> None:
    session_id = started(client)["id"]

    assert client.post(f"/sessions/{session_id}/accept").status_code == 202
    state = settled(client, session_id)

    assert (state["phase"], state["turn_status"], state["open_items"]) == ("complete", "idle", [])
    assert state["outputs"] == [
        {"flow": "main", "label": "Main flow", "files": ["diagram.bpmn", "diagram.html", "graph.json"]}
    ]
    assert client.get(f"/sessions/{session_id}/outputs").json() == state["outputs"]

    bpmn = client.get(f"/sessions/{session_id}/outputs/main/diagram.bpmn")
    assert ET.fromstring(bpmn.text).tag == f"{{{BPMN_NS}}}definitions"
    assert 'filename="main-diagram.bpmn"' in bpmn.headers["content-disposition"]
    assert "<html" in client.get(f"/sessions/{session_id}/outputs/main/diagram.html").text
    assert client.get(f"/sessions/{session_id}/outputs/main/graph.json").json()["process_name"] == DOMAIN_PROCESS


def test_only_the_offered_files_can_be_downloaded(client: TestClient) -> None:
    session_id = started(client)["id"]
    client.post(f"/sessions/{session_id}/accept")
    settled(client, session_id)

    assert client.get(f"/sessions/{session_id}/outputs/main/validation.json").status_code == 404
    assert client.get(f"/sessions/{session_id}/outputs/main/..%2F..%2Fsession.json").status_code == 404
    assert client.get(f"/sessions/{session_id}/outputs/off_label_review/diagram.bpmn").status_code == 404
    assert client.get(f"/sessions/{session_id}/outputs/no%20such/diagram.bpmn").status_code == 404


def test_nothing_is_offered_before_the_session_is_finished(client: TestClient) -> None:
    state = started(client)

    assert state["outputs"] == []
    assert client.get(f"/sessions/{state['id']}/outputs/main/diagram.bpmn").status_code == 404


def test_a_finished_session_takes_no_more_messages(client: TestClient) -> None:
    session_id = started(client)["id"]
    client.post(f"/sessions/{session_id}/accept")
    settled(client, session_id)

    for path, body in (
        ("messages", {"text": "one more"}),
        ("close", None),
        ("accept", None),
        ("focus", {"focus": "main"}),
    ):
        assert client.post(f"/sessions/{session_id}/{path}", json=body).status_code == 409, path


def test_a_session_with_no_flow_cannot_be_accepted(client: TestClient, fake: FakeConversations) -> None:
    fake.scripts[EXTRACTOR].clear()
    broken = patch(*first_patch().operations[:1])
    fake.extractor(broken, broken, broken)
    session_id = started(client)["id"]

    assert client.post(f"/sessions/{session_id}/accept").status_code == 409


def test_the_built_page_is_served_at_the_root_and_the_api_keeps_its_own_paths(
    store: FileSessionStore, tmp_path: Path
) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<h1>the conversation</h1>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("console.log('page')", encoding="utf-8")
    app = create_app(
        conversations=FakeConversations(), session_store=store, domain_dir=DOMAIN_DIR, frontend_dir=frontend
    )

    with TestClient(app) as client:
        assert client.get("/").text == "<h1>the conversation</h1>"
        assert client.get("/assets/app.js").text == "console.log('page')"
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/processes").json()[0]["id"] == DOMAIN_PROCESS
        assert client.get("/sessions/nosuchsession").status_code == 404, "an API 404, not the page"


def test_the_service_runs_without_a_built_page(client: TestClient) -> None:
    """How the tests and a ``vite dev`` session both use it: the API alone."""
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
