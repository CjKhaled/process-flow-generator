"""The hosted demo's HTTP service, with the model and the layouter injected.

Both of the pipeline's outside dependencies are constructor arguments, so a run
here reaches the real extractor loop, the real validator, the real BPMN mapping
and the real page builder -- with no API key, no network and no Node. What is
faked is only what this project does not own.

A run is executed on a worker thread and polled, so every test that starts one
waits for it. :func:`finished` is that wait, with a timeout, so a stuck run fails
the suite instead of hanging it.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from bpmn.autolayout import Layouter
from bpmn.decisions import DIAMOND
from extractors.errors import SchemaCallError
from ir.models import ProcessGraph
from tests.conftest import ENROLLMENT_DIR, decision_layouter, echo_layouter

SOURCE = "The HCP faxes a PEF to CM360, who transcribes it."
TIMEOUT_S = 10.0


@pytest.fixture
def processes_root(tmp_path: Path) -> Path:
    """A throwaway copy of the real enrollment folder.

    The real metadata and skeleton, because the extractor is validated against
    the skeleton and the BPMN mapping is validated against the actors: a
    hand-written stand-in for either would be testing the stand-in.
    """
    root = tmp_path / "processes"
    root.mkdir()
    (root / "enrollment").mkdir()
    for name in ("metadata.yaml", "skeleton.json"):
        (root / "enrollment" / name).write_text((ENROLLMENT_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return root


@pytest.fixture
def client(processes_root: Path, valid_graph: ProcessGraph) -> Iterator[TestClient]:
    """A service that answers every run with the same sound graph."""
    with TestClient(app(processes_root, lambda prompt: valid_graph)) as running:
        yield running


def app(processes_root: Path, call: Any, site_dir: Path | None = None, layout: Layouter = echo_layouter) -> FastAPI:
    """Build the service with both outside dependencies replaced."""
    return create_app(
        call=call,
        layout=layout,
        processes_root=processes_root,
        site_dir=site_dir or processes_root / "no-site-here",
    )


def finished(client: TestClient, run_id: str) -> dict[str, Any]:
    """Poll until the run stops moving, as the page does.

    Raises:
        AssertionError: If it has not finished within the timeout, which means
            the worker is stuck and the page would spin for ever.
    """
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        state = client.get(f"/runs/{run_id}").json()
        if state["status"] in {"done", "failed"}:
            return dict(state)
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish within {TIMEOUT_S}s")


def start(client: TestClient, process: str = "enrollment", source: str = SOURCE) -> dict[str, Any]:
    """Post a run and return the response body."""
    return dict(client.post("/runs", json={"process": process, "source": source}).json())


def test_health_answers_without_touching_anything(client: TestClient) -> None:
    """What the page pings on load to wake a sleeping instance."""
    assert client.get("/health").json() == {"status": "ok"}


def test_the_processes_are_listed_for_the_picker(client: TestClient) -> None:
    assert client.get("/processes").json() == [{"name": "enrollment", "display_name": "Intake & Enrollment"}]


def test_a_run_finishes_with_a_page_payload(client: TestClient) -> None:
    state = finished(client, start(client)["id"])

    assert state["status"] == "done"
    assert state["result"]["title"] == "Intake & Enrollment"
    assert state["result"]["diagram"].startswith("<?xml")


def test_the_hosted_diagram_has_its_decisions_redrawn(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The hosted page and the offline one must show the same drawing, redrawn decisions included."""
    with TestClient(app(processes_root, lambda _prompt: valid_graph, layout=decision_layouter)) as running:
        result = finished(running, start(running)["id"])["result"]

    assert f'width="{int(DIAMOND[0])}" height="{int(DIAMOND[1])}"' in result["diagram"]


def test_the_payload_flags_what_the_validator_raised(client: TestClient) -> None:
    """The fixture graph omits a required subprocess, so it comes back with a question."""
    result = finished(client, start(client)["id"])["result"]

    assert result["count"] >= 1
    assert "missing_info" in result["questions"]


def test_a_queued_run_reports_where_it_has_got_to(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The page shows this while it waits, so it has to be a sentence and not a code."""
    seen = []

    def slow(prompt: str) -> ProcessGraph:
        seen.append(prompt)
        time.sleep(0.2)
        return valid_graph

    with TestClient(app(processes_root, slow)) as client:
        run_id = start(client)["id"]
        state = client.get(f"/runs/{run_id}").json()

        assert state["status"] in {"queued", "extracting"}
        assert state["label"] and state["label"][0].isupper()
        finished(client, run_id)


def test_a_failed_extraction_says_why(processes_root: Path) -> None:
    """A model that never produces a valid graph is a failed run, not a hung one."""

    def refuses(prompt: str) -> ProcessGraph:
        raise SchemaCallError("the response was not a graph")

    with TestClient(app(processes_root, refuses)) as client:
        state = finished(client, start(client)["id"])

        assert state["status"] == "failed"
        assert "the response was not a graph" in state["detail"]
        assert state["result"] is None


def test_an_unknown_process_is_refused_before_any_model_call(client: TestClient) -> None:
    response = client.post("/runs", json={"process": "onboarding", "source": SOURCE})

    assert response.status_code == 404
    assert "onboarding" in response.json()["detail"]


def test_an_empty_description_is_refused(client: TestClient) -> None:
    response = client.post("/runs", json={"process": "enrollment", "source": "   "})

    assert response.status_code == 422


def test_an_oversized_description_is_refused(client: TestClient) -> None:
    """Not a security control -- the difference between a cheap call and a costly one."""
    response = client.post("/runs", json={"process": "enrollment", "source": "x" * 20_001})

    assert response.status_code == 413
    assert "20,000" in response.json()["detail"]


def test_an_unknown_run_is_not_a_run_that_is_still_going(client: TestClient) -> None:
    """The page must be told to stop polling, not left waiting on a run nobody has."""
    assert client.get("/runs/nosuchrun").status_code == 404


def test_the_site_is_served_when_one_has_been_built(processes_root: Path, valid_graph: ProcessGraph) -> None:
    """The one-URL deployment: the service hosts the page that calls it."""
    site = processes_root.parent / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>the page</h1>", encoding="utf-8")

    with TestClient(app(processes_root, lambda prompt: valid_graph, site_dir=site)) as client:
        assert client.get("/").text == "<h1>the page</h1>"
        assert client.get("/health").json() == {"status": "ok"}, "the API must still own its own paths"
