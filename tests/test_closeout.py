"""Close-out: what a session hands to stages 2 and 3, and that they accept it.

The layouter and the viewer's files are injected, as everywhere else, so these
run with no Node. What is real is everything this project owns: the composition,
the folder layout, and stage 2's and stage 3's own loaders and translators
reading what was written.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bpmn.autolayout import Layouter
from bpmn.document import BPMN_NS
from ir.models import ProcessGraph
from ir.process_config import load_process_config
from ir.skeleton import load_skeleton
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, TopicStatus
from pipelines import stage2
from render.assets import ViewerAssets
from session.closeout import (
    NothingToDraw,
    compose_flow,
    finalise,
    flow_scopes,
    list_outputs,
    write_flow,
)
from session.ledger import TopicUpdate, apply_updates, open_items
from session.models import LearnedTerm, Phase, Session
from session.orchestrator import new_session
from session.store import FileSessionStore
from tests.master_graph import master_session
from validators.report import FindingCode, ValidationReport

SUBS = ("duplicate_handling", "off_label_review", "missing_info_hcp", "missing_info_patient")


@pytest.fixture
def session(domain: DomainKnowledge) -> Session:
    return master_session(domain)


def finished(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> tuple[Session, FileSessionStore]:
    store = FileSessionStore(tmp_path / "sessions")
    return finalise(session, domain, store, layout=layouter, assets=viewer_assets), store


def test_a_session_has_a_main_flow_and_one_flow_per_subprocess_with_steps(
    session: Session, domain: DomainKnowledge
) -> None:
    assert flow_scopes(session, domain) == (MAIN_SCOPE, *SUBS)

    session.graph = session.graph.model_copy(
        update={
            "nodes": tuple(
                n.model_copy(update={"subprocess": None}) if n.subprocess == "off_label_review" else n
                for n in session.graph.nodes
            )
        }
    )

    assert "off_label_review" not in flow_scopes(session, domain)


def test_the_main_flows_config_names_the_process_and_every_lane_it_uses(
    session: Session, domain: DomainKnowledge
) -> None:
    config = compose_flow(session, domain, MAIN_SCOPE).config

    assert (config.process_name, config.display_name) == ("enrollment_and_intake", "Intake & Enrollment")
    assert set(config.actors) == {"HCP", "Vendor", "PSM", "Manager", "CRM"}
    assert config.default_actor == "CRM"
    assert config.model_id is None


def test_lanes_are_ordered_by_the_processs_usual_personas(session: Session, domain: DomainKnowledge) -> None:
    """So the diagram reads the conventional way: the office at the top, the system at the bottom."""
    assert list(compose_flow(session, domain, MAIN_SCOPE).config.actors) == ["HCP", "Vendor", "PSM", "Manager", "CRM"]


def test_a_lane_with_no_known_persona_comes_after_those_with_one(session: Session, domain: DomainKnowledge) -> None:
    session.lanes = [
        lane.model_copy(update={"persona": None}) if lane.name == "Vendor" else lane for lane in session.lanes
    ]

    assert list(compose_flow(session, domain, MAIN_SCOPE).config.actors)[-1] == "Vendor"


def test_a_lane_is_described_by_its_persona_and_by_what_the_user_said(
    session: Session, domain: DomainKnowledge
) -> None:
    session.lanes = [
        lane.model_copy(update={"description": "Assigned by ZIP."}) if lane.name == "PSM" else lane
        for lane in session.lanes
    ]

    described = compose_flow(session, domain, MAIN_SCOPE).config.actors["PSM"]

    assert described == f"{domain.personas['hub_case_owner'].lane_description} Assigned by ZIP."


def test_the_glossary_is_the_domains_plus_what_the_session_learned(session: Session, domain: DomainKnowledge) -> None:
    session.glossary.append(LearnedTerm(term="JCRM", meaning="another name for the CRM"))
    session.glossary.append(LearnedTerm(term="PEF", meaning="our start form"))

    glossary = compose_flow(session, domain, MAIN_SCOPE).config.glossary

    assert glossary["JCRM"] == "another name for the CRM"
    assert glossary["PEF"] == "our start form", "what this program means by a term beats the general meaning"
    assert glossary["NIGO"] == domain.glossary["NIGO"].meaning


def test_the_main_skeleton_lists_the_subprocesses_that_have_steps_in_their_hand_off_lane(
    session: Session, domain: DomainKnowledge
) -> None:
    skeleton = compose_flow(session, domain, MAIN_SCOPE).skeleton

    assert [(spec.name, spec.label, spec.actor) for spec in skeleton.subprocesses] == [
        ("duplicate_handling", "Duplicate handling", "Vendor"),
        ("off_label_review", "Off-label review", "Vendor"),
        ("missing_info_hcp", "Missing information outreach (HCP)", "CRM"),
        ("missing_info_patient", "Missing information outreach (patient)", "CRM"),
    ]


def test_the_main_graph_is_the_master_graph_untouched(session: Session, domain: DomainKnowledge) -> None:
    assert compose_flow(session, domain, MAIN_SCOPE).graph is session.graph


@pytest.mark.parametrize("scope", SUBS)
def test_a_subprocess_flow_is_its_slice_with_an_empty_skeleton(
    session: Session, domain: DomainKnowledge, scope: str
) -> None:
    bundle = compose_flow(session, domain, scope)

    assert bundle.skeleton.subprocesses == ()
    assert bundle.config.process_name == f"enrollment_and_intake_{scope}"
    assert bundle.config.display_name == f"Intake & Enrollment: {domain.process.scope_label(scope)}"
    assert {n.actor for n in bundle.graph.nodes} <= set(bundle.config.actors)
    assert bundle.report.is_structurally_valid


def test_a_subprocess_flow_declares_only_the_lanes_it_uses_and_the_default(
    session: Session, domain: DomainKnowledge
) -> None:
    assert list(compose_flow(session, domain, "duplicate_handling").config.actors) == ["Vendor", "PSM", "CRM"]


def test_the_report_carries_the_graphs_open_points_and_the_ledgers_for_that_scope(
    session: Session, domain: DomainKnowledge
) -> None:
    session.ledger = apply_updates(
        session.ledger,
        [
            TopicUpdate("off_label_review.notification", TopicStatus.DEFERRED),
            TopicUpdate("consent.validity", TopicStatus.DEFERRED),
        ],
        [],
    )

    report = compose_flow(session, domain, "off_label_review").report
    messages = [finding.message for finding in report.resolution]

    assert report.structural == ()
    assert {f.code for f in report.resolution} == {
        FindingCode.NEEDS_CLARIFICATION,
        FindingCode.OPEN_TOPIC,
        FindingCode.DEFERRED_TOPIC,
    }
    assert any("'Who is told' was put off" in message for message in messages)
    assert not any("Consent validity" in message for message in messages), "another scope's topic"


def test_a_finding_never_points_at_a_step_that_is_not_in_its_flow(session: Session, domain: DomainKnowledge) -> None:
    """A topic links to steps by shared statements, so it can link to one outside its own scope."""
    session.ledger = [
        entry.model_copy(update={"status": TopicStatus.DEFERRED, "node_ids": ("key_form", "ol_call")})
        if entry.topic_id == "off_label_review.notification"
        else entry
        for entry in session.ledger
    ]

    report = compose_flow(session, domain, "off_label_review").report
    deferred = next(f for f in report.findings if f.code is FindingCode.DEFERRED_TOPIC)

    assert deferred.node_ids == ("ol_call",)


def test_a_session_with_no_flow_has_nothing_to_finish(domain: DomainKnowledge, tmp_path: Path) -> None:
    empty = new_session("empty", domain)

    with pytest.raises(NothingToDraw):
        compose_flow(empty, domain, MAIN_SCOPE)
    with pytest.raises(NothingToDraw):
        compose_flow(master_session(domain), domain, "no_such_subprocess")


def test_a_written_flow_is_read_back_by_the_stages_own_loaders(
    session: Session, domain: DomainKnowledge, tmp_path: Path
) -> None:
    """The contract with stages 2 and 3 is their loaders, so those are what read the folder back."""
    for scope in flow_scopes(session, domain):
        bundle = compose_flow(session, domain, scope)
        folder = tmp_path / scope

        write_flow(folder, bundle)

        assert load_process_config(folder) == bundle.config
        assert load_skeleton(folder / "skeleton.json") == bundle.skeleton
        graph = ProcessGraph.model_validate(json.loads((folder / "outputs" / "graph.json").read_text("utf-8")))
        assert graph == bundle.graph
        report = ValidationReport.model_validate(
            json.loads((folder / "outputs" / "validation.json").read_text("utf-8"))
        )
        assert report == bundle.report


def test_a_written_flow_can_be_drawn_by_the_stage_2_command_itself(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter
) -> None:
    """No second copy of a stage: the folder close-out writes is one the CLI stage runs on unchanged."""
    for scope in flow_scopes(session, domain):
        write_flow(tmp_path / scope, compose_flow(session, domain, scope))

        written = stage2.run(scope, tmp_path, layout=layouter)

        assert ET.fromstring(written.read_text("utf-8")).tag == f"{{{BPMN_NS}}}definitions"


def test_finalising_writes_bpmn_and_html_for_every_flow(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    done, store = finished(session, domain, tmp_path, layouter, viewer_assets)

    for scope in (MAIN_SCOPE, *SUBS):
        outputs = store.path_for_outputs(done.id, scope) / "outputs"
        assert ET.fromstring((outputs / "diagram.bpmn").read_text("utf-8")).tag == f"{{{BPMN_NS}}}definitions"
        assert "<html" in (outputs / "diagram.html").read_text("utf-8")
        assert (outputs / "graph.json").is_file() and (outputs / "validation.json").is_file()


def test_the_main_diagram_draws_each_subprocess_as_one_box(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    done, store = finished(session, domain, tmp_path, layouter, viewer_assets)
    diagram = ET.fromstring(
        (store.path_for_outputs(done.id, MAIN_SCOPE) / "outputs" / "diagram.bpmn").read_text("utf-8")
    )

    boxes = {element.get("name") for element in diagram.iter(f"{{{BPMN_NS}}}subProcess")}
    tasks = {element.get("name") for element in diagram.iter(f"{{{BPMN_NS}}}task")}

    assert boxes == {domain.process.scope_label(scope) for scope in SUBS}
    assert "Mi Fax" not in tasks and "Key Form" in tasks


def test_a_subprocess_diagram_draws_its_own_steps(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    done, store = finished(session, domain, tmp_path, layouter, viewer_assets)
    path = store.path_for_outputs(done.id, "missing_info_hcp") / "outputs" / "diagram.bpmn"
    diagram = ET.fromstring(path.read_text("utf-8"))

    assert {e.get("name") for e in diagram.iter(f"{{{BPMN_NS}}}task")} == {"Mi Fax", "Mi Escalate"}
    assert list(diagram.iter(f"{{{BPMN_NS}}}subProcess")) == []
    assert "Return to main flow: Gw Consent" in {e.get("name") for e in diagram.iter(f"{{{BPMN_NS}}}endEvent")}


def test_the_page_lists_the_flows_open_questions_by_their_message(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    """Stage 3 prints any finding code it is given, so the conversation's codes need no mapping there."""
    done, store = finished(session, domain, tmp_path, layouter, viewer_assets)
    html = (store.path_for_outputs(done.id, "off_label_review") / "outputs" / "diagram.html").read_text("utf-8")

    assert "open topic" in html
    assert "&#x27;Off-label outcome&#x27; was not covered" in html
    assert "needs clarification" in html


def test_finalising_accepts_everything_still_open_and_completes_the_session(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    before = {item.key for item in open_items(session, domain)}
    assert "node:ol_open" in before

    done, _ = finished(session, domain, tmp_path, layouter, viewer_assets)

    assert done.phase is Phase.COMPLETE
    assert before <= set(done.accepted_open_items)
    assert open_items(done, domain) == ()
    assert session.phase is not Phase.COMPLETE, "the session given is never modified"


def test_nothing_is_written_if_any_flow_cannot_be_drawn(
    session: Session, domain: DomainKnowledge, tmp_path: Path, viewer_assets: ViewerAssets
) -> None:
    calls = []

    def fails_on_the_third(xml: str) -> str:
        calls.append(xml)
        if len(calls) == 3:
            raise RuntimeError("the layouter rejected the diagram")
        return xml

    store = FileSessionStore(tmp_path / "sessions")
    with pytest.raises(RuntimeError, match="rejected"):
        finalise(session, domain, store, layout=fails_on_the_third, assets=viewer_assets)

    assert not (tmp_path / "sessions").exists()


def test_outputs_are_listed_per_flow_once_they_exist(
    session: Session, domain: DomainKnowledge, tmp_path: Path, layouter: Layouter, viewer_assets: ViewerAssets
) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    assert list_outputs(session, domain, store) == []

    done, store = finished(session, domain, tmp_path, layouter, viewer_assets)
    listed = list_outputs(done, domain, store)

    assert [entry["flow"] for entry in listed] == [MAIN_SCOPE, *SUBS]
    assert listed[0] == {"flow": "main", "label": "Main flow", "files": ["diagram.bpmn", "diagram.html", "graph.json"]}
