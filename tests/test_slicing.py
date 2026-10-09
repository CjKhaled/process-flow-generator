"""Cutting a subprocess out of the master graph."""

import pytest

from agents.extractor import check
from ir.models import EdgeType, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from knowledge.loader import DomainKnowledge
from session.slicing import (
    EMPTY_SKELETON,
    EXIT_PREFIX,
    RETURN_PREFIX,
    START_ID,
    flow_name,
    handoff_lane,
    members,
    slice_subprocess,
)
from tests.master_graph import master_graph, master_session
from validators.graph import validate
from validators.report import FindingCode

ALL = ("duplicate_handling", "off_label_review", "missing_info_hcp", "missing_info_patient")


def cut(domain: DomainKnowledge, subprocess_id: str) -> ProcessGraph:
    sub = domain.process.subprocess(subprocess_id)
    assert sub is not None
    sliced = slice_subprocess(master_graph(), sub, domain.process)
    assert sliced is not None
    return sliced


def test_the_fixture_is_itself_a_valid_session_graph(domain: DomainKnowledge) -> None:
    session = master_session(domain)

    assert check(session.graph, session, domain).structural == ()


def test_the_process_declares_exactly_the_four_subprocesses_sliced_here(domain: DomainKnowledge) -> None:
    assert domain.process.subprocess_ids == ALL


@pytest.mark.parametrize("subprocess_id", ALL)
def test_every_slice_is_a_structurally_valid_graph(domain: DomainKnowledge, subprocess_id: str) -> None:
    """It has to be: stages 2 and 3 are handed it as a process in its own right."""
    assert validate(cut(domain, subprocess_id), EMPTY_SKELETON).is_structurally_valid


@pytest.mark.parametrize("subprocess_id", ALL)
def test_a_slice_starts_at_one_synthesised_start_labelled_with_the_entry(
    domain: DomainKnowledge, subprocess_id: str
) -> None:
    sliced = cut(domain, subprocess_id)
    starts = [n for n in sliced.nodes if n.type is NodeType.START]

    assert [(n.id, n.origin) for n in starts] == [(START_ID, NodeOrigin.SLICE)]
    assert starts[0].label == domain.process.subprocess(subprocess_id).entry  # type: ignore[union-attr]
    assert sliced.nodes[0] is starts[0]


@pytest.mark.parametrize("subprocess_id", ALL)
def test_a_slice_keeps_no_subprocess_tag_and_is_named_for_its_flow(domain: DomainKnowledge, subprocess_id: str) -> None:
    """Within its own flow a step is just a step; a tag would send stage 2 looking for a box."""
    sliced = cut(domain, subprocess_id)

    assert {n.subprocess for n in sliced.nodes} == {None}
    assert sliced.process_name == f"enrollment_and_intake_{subprocess_id}"
    assert FindingCode.UNKNOWN_SUBPROCESS not in {f.code for f in validate(sliced, EMPTY_SKELETON).findings}


def test_the_tagged_steps_and_the_edges_among_them_are_kept_as_they_were(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "missing_info_hcp")
    original = {n.id: n for n in master_graph().nodes}

    kept = [n for n in sliced.nodes if n.origin is NodeOrigin.SOURCE]

    assert [n.id for n in kept] == ["mi_fax", "gw_received", "mi_escalate"]
    assert all(n == original[n.id].model_copy(update={"subprocess": None}) for n in kept)
    assert ("mi_escalate", "mi_fax") in {(e.from_id, e.to_id) for e in sliced.edges}, "the loop survives"


def test_an_edge_back_to_the_main_flow_ends_at_a_terminal_naming_where_it_returns(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "missing_info_hcp")
    exits = {n.id: n for n in sliced.nodes if n.id.startswith(EXIT_PREFIX)}

    returned = exits[f"{EXIT_PREFIX}gw_consent"]
    assert returned.label == f"{RETURN_PREFIX}Gw Consent"
    assert (returned.type, returned.origin, returned.status) == (NodeType.TERMINAL, NodeOrigin.SLICE, NodeStatus.STATED)
    assert returned.actor == "CRM", "the lane that owns the outcome: whoever picks the work up"
    branch = next(e for e in sliced.edges if e.to_id == returned.id)
    assert (branch.from_id, branch.type, branch.condition) == (
        "gw_received",
        EdgeType.BRANCH,
        "the information arrives",
    )


def test_an_edge_out_to_a_process_end_keeps_that_ends_own_label(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "duplicate_handling")
    exits = {n.id: n.label for n in sliced.nodes if n.id.startswith(EXIT_PREFIX)}

    assert exits == {
        f"{EXIT_PREFIX}gw_eligible": f"{RETURN_PREFIX}Gw Eligible",
        f"{EXIT_PREFIX}end_closed": "Closed, not enrolled",
    }


def test_a_slice_handing_off_to_another_subprocess_ends_where_it_leaves(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "missing_info_hcp")

    assert f"{EXIT_PREFIX}pt_letter" in {n.id for n in sliced.nodes}
    assert "pt_letter" not in {n.id for n in sliced.nodes}


def test_a_terminal_inside_the_subprocess_is_kept_open_question_and_all(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "off_label_review")
    inside = next(n for n in sliced.nodes if n.id == "ol_open")

    assert (inside.origin, inside.status) == (NodeOrigin.RULE, NodeStatus.NEEDS_CLARIFICATION)
    assert "does not confirm" in (inside.detail or "")


def test_a_note_on_a_step_comes_with_it(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "off_label_review")

    assert "ol_note" in {n.id for n in sliced.nodes}
    assert ("ol_note", "ol_call", EdgeType.ANNOTATES) in {(e.from_id, e.to_id, e.type) for e in sliced.edges}


def test_a_subprocess_entered_at_two_points_has_its_start_wired_to_both(domain: DomainKnowledge) -> None:
    sliced = cut(domain, "missing_info_patient")
    from_start = sorted((e.order, e.to_id) for e in sliced.edges if e.from_id == START_ID)

    assert from_start == [(0, "pt_call"), (1, "pt_letter")]
    assert sliced.nodes[0].actor == "PSM", "the lane of the first step entered"


def test_a_subprocess_with_no_steps_has_no_slice(domain: DomainKnowledge) -> None:
    sub = domain.process.subprocess("off_label_review")
    assert sub is not None
    untagged = master_graph().model_copy(
        update={"nodes": tuple(n.model_copy(update={"subprocess": None}) for n in master_graph().nodes)}
    )

    assert slice_subprocess(untagged, sub, domain.process) is None
    assert members(untagged, "off_label_review") == ()


def test_slicing_never_modifies_the_master_graph(domain: DomainKnowledge) -> None:
    original = master_graph()
    sub = domain.process.subprocess("duplicate_handling")
    assert sub is not None

    slice_subprocess(original, sub, domain.process)

    assert original == master_graph()


def test_a_collapsed_box_sits_in_the_lane_of_whoever_hands_off_to_it(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    process = domain.process

    lanes = {sub.id: handoff_lane(session, process, sub) for sub in process.subprocesses}

    assert lanes == {
        "duplicate_handling": "Vendor",
        "off_label_review": "Vendor",
        "missing_info_hcp": "CRM",
        "missing_info_patient": "CRM",
    }


def test_with_no_hand_off_yet_the_box_falls_to_the_personas_lane_then_the_default(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.graph = session.graph.model_copy(update={"edges": ()})
    sub = domain.process.subprocess("missing_info_hcp")
    assert sub is not None

    assert handoff_lane(session, domain.process, sub) == "PSM"

    session.lanes = [lane for lane in session.lanes if lane.name != "PSM"]

    assert handoff_lane(session, domain.process, sub) == "CRM"


def test_flow_names(domain: DomainKnowledge) -> None:
    assert flow_name(domain.process) == "enrollment_and_intake"
    assert flow_name(domain.process, "off_label_review") == "enrollment_and_intake_off_label_review"
