"""The live views: the collapse, the arrows, and the rationale behind each step."""

from ir.models import NodeType
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, TopicStatus
from session.ledger import TopicUpdate, apply_updates, link_nodes
from session.models import Statement, StatementOrigin
from session.orchestrator import new_session
from session.views import BOX_PREFIX, FlowView, main_view, session_views
from tests.builders import ref
from tests.master_graph import TEXT, master_session

SUBS = ("duplicate_handling", "off_label_review", "missing_info_hcp", "missing_info_patient")


def ids(view: FlowView) -> list[str]:
    return [node.id for node in view.nodes]


def arrows(view: FlowView) -> dict[tuple[str, str], str | None]:
    return {(edge.source, edge.target): edge.label for edge in view.edges}


def test_there_is_nothing_to_show_before_the_first_turn(domain: DomainKnowledge) -> None:
    assert session_views(new_session("s", domain), domain) == []


def test_the_views_are_the_main_flow_then_each_subprocess_with_steps(domain: DomainKnowledge) -> None:
    views = session_views(master_session(domain), domain)

    assert [(view.id, view.label) for view in views] == [
        (MAIN_SCOPE, "Main flow"),
        ("duplicate_handling", "Duplicate handling"),
        ("off_label_review", "Off-label review"),
        ("missing_info_hcp", "Missing information outreach (HCP)"),
        ("missing_info_patient", "Missing information outreach (patient)"),
    ]


def test_a_subprocess_with_no_steps_gets_no_view_and_no_box(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.graph = session.graph.model_copy(
        update={
            "nodes": tuple(
                n.model_copy(update={"subprocess": None}) if n.subprocess == "off_label_review" else n
                for n in session.graph.nodes
            )
        }
    )

    views = session_views(session, domain)

    assert "off_label_review" not in [view.id for view in views]
    assert f"{BOX_PREFIX}off_label_review" not in ids(views[0])
    assert "ol_call" in ids(views[0])


def test_the_main_view_draws_each_subprocess_as_one_box_where_its_first_step_stood(domain: DomainKnowledge) -> None:
    view = main_view(master_session(domain), domain)

    assert ids(view) == [
        "start",
        "key_form",
        "gw_duplicate",
        "sub:duplicate_handling",
        "gw_eligible",
        "sub:off_label_review",
        "gw_missing",
        "sub:missing_info_hcp",
        "gw_consent",
        "sub:missing_info_patient",
        "enroll",
        "end_enrolled",
        "end_closed",
    ]
    box = next(node for node in view.nodes if node.id == "sub:off_label_review")
    assert (box.kind, box.label, box.subprocess_id, box.lane) == (
        "subprocess",
        "Off-label review",
        "off_label_review",
        "Vendor",
    )


def test_edges_leaving_a_box_are_kept_so_the_main_flow_reads_as_one_line(domain: DomainKnowledge) -> None:
    """The difference from stage 2's fold, which ends each path at its box."""
    found = arrows(main_view(master_session(domain), domain))

    assert ("sub:duplicate_handling", "gw_eligible") in found
    assert ("sub:off_label_review", "gw_missing") in found
    assert ("sub:missing_info_hcp", "sub:missing_info_patient") in found, "one box handing off to another"


def test_edges_inside_a_box_are_not_drawn_and_parallel_ones_are_merged(domain: DomainKnowledge) -> None:
    view = main_view(master_session(domain), domain)
    pairs = [(edge.source, edge.target) for edge in view.edges]

    assert len(pairs) == len(set(pairs)), "pt_call and pt_letter both feed the same box"
    assert all(source != target for source, target in pairs)
    assert not {"mi_fax", "gw_received", "pt_call"} & {end for pair in pairs for end in pair}


def test_a_merged_edge_keeps_its_label_only_if_every_edge_agreed(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    found = arrows(main_view(session, domain))

    assert found[("gw_duplicate", "sub:duplicate_handling")] == "a possible match is found"
    assert found[("sub:missing_info_patient", "enroll")] == "the patient responds"

    session.graph = session.graph.model_copy(
        update={
            "edges": tuple(
                e.model_copy(update={"type": "branch", "condition": "by letter"}) if e.from_id == "pt_letter" else e
                for e in session.graph.edges
            )
        }
    )
    # Two different reasons for reaching the same box from inside it: still internal, still not drawn.
    assert ("sub:missing_info_patient", "sub:missing_info_patient") not in arrows(main_view(session, domain))


def test_an_arrow_says_the_answer_then_the_condition_then_nothing(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.graph = session.graph.model_copy(
        update={
            "edges": tuple(
                e.model_copy(update={"answer": "yes"}) if (e.from_id, e.to_id) == ("gw_consent", "enroll") else e
                for e in session.graph.edges
            )
        }
    )
    found = arrows(main_view(session, domain))

    assert found[("gw_consent", "enroll")] == "Yes"
    assert found[("gw_eligible", "gw_missing")] == "the diagnosis is on-label"
    assert found[("start", "key_form")] is None


def test_annotations_are_not_drawn_but_become_notes_on_the_step_they_describe(domain: DomainKnowledge) -> None:
    review = next(view for view in session_views(master_session(domain), domain) if view.id == "off_label_review")

    assert "ol_note" not in ids(review)
    assert all(node.kind != NodeType.ANNOTATION for node in review.nodes)
    assert review.rationale["ol_call"].notes == ("Status = REVIEW",)


def test_a_subprocess_view_is_its_slice(domain: DomainKnowledge) -> None:
    review = next(view for view in session_views(master_session(domain), domain) if view.id == "off_label_review")

    assert ids(review) == ["slice_start", "ol_call", "gw_confirms", "ol_open", "slice_exit_gw_missing"]
    assert review.nodes[0].origin == "slice"
    assert review.nodes[-1].label == "Return to main flow: Gw Missing"


def test_a_step_with_an_open_question_is_flagged_and_so_is_the_box_holding_it(domain: DomainKnowledge) -> None:
    views = session_views(master_session(domain), domain)
    box = next(node for node in views[0].nodes if node.id == "sub:off_label_review")
    inside = next(node for node in views[2].nodes if node.id == "ol_open")

    assert box.open_question and box.status == "needs_clarification"
    assert inside.open_question and inside.origin == "rule"
    assert not next(node for node in views[0].nodes if node.id == "sub:duplicate_handling").open_question


def test_a_boxs_rationale_says_what_enters_it_and_how_much_is_open(domain: DomainKnowledge) -> None:
    box = main_view(master_session(domain), domain).rationale["sub:off_label_review"]

    assert box.entry == "The submission doesn't clearly meet the eligibility criteria"
    assert (box.step_count, box.open_count) == (3, 1)


def test_a_steps_rationale_quotes_the_statement_it_came_from(domain: DomainKnowledge) -> None:
    line = main_view(master_session(domain), domain).rationale["key_form"].evidence[0]

    assert line.model_dump() == {
        "statement_id": "s_0001",
        "quote": "The whole process",
        "statement_text": TEXT,
        "restatement": None,
        "turn": 1,
        "origin": "initial_description",
    }


def test_evidence_from_an_answer_carries_its_turn_and_marks_the_step(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.corpus.append(
        Statement(
            id="s_0002",
            origin=StatementOrigin.ANSWER,
            turn=4,
            raw_text="Yeah, by fax.",
            restatement="The form is keyed after arriving by fax.",
        )
    )
    session.graph = session.graph.model_copy(
        update={
            "nodes": tuple(
                n.model_copy(update={"evidence": (*n.evidence, ref("s_0002", "by fax"))}) if n.id == "key_form" else n
                for n in session.graph.nodes
            )
        }
    )
    view = main_view(session, domain)
    line = view.rationale["key_form"].evidence[-1]

    assert (line.turn, line.origin, line.restatement) == (4, "answer", "The form is keyed after arriving by fax.")
    assert next(node for node in view.nodes if node.id == "key_form").from_answer
    assert not next(node for node in view.nodes if node.id == "start").from_answer


def test_a_steps_rationale_carries_its_open_question_and_alternatives(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.graph = session.graph.model_copy(
        update={
            "nodes": tuple(
                n.model_copy(update={"alternatives": ("archived", "not entered")}) if n.id == "dup_attach" else n
                for n in session.graph.nodes
            )
        }
    )
    views = {view.id: view for view in session_views(session, domain)}

    assert "does not confirm" in (views["off_label_review"].rationale["ol_open"].open_question or "")
    assert views["duplicate_handling"].rationale["dup_attach"].alternatives == ("archived", "not entered")
    assert views[MAIN_SCOPE].rationale["key_form"].open_question is None


def test_a_steps_rationale_names_the_coverage_topics_it_bears_on(domain: DomainKnowledge) -> None:
    session = master_session(domain)
    session.ledger = link_nodes(
        apply_updates(session.ledger, [TopicUpdate("intake.keying", TopicStatus.PRESENT, ("s_0001",))], []),
        session.graph,
    )

    assert main_view(session, domain).rationale["key_form"].topics == ("Who keys the form",)


def test_every_drawn_node_has_a_rationale_and_every_edge_joins_drawn_nodes(domain: DomainKnowledge) -> None:
    for view in session_views(master_session(domain), domain):
        drawn = set(ids(view))

        assert set(view.rationale) == drawn, view.id
        assert all(edge.source in drawn and edge.target in drawn for edge in view.edges), view.id
        assert len({edge.id for edge in view.edges}) == len(view.edges)
