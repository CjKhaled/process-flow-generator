"""A whole conversation, turn by turn, with every agent scripted.

The real pipeline, the real validators, the real ledger and the real knowledge
base; only the three model calls are faked. Each test is one thing a session has
to get right, told as the turns that show it.
"""

import pytest

from agents.interpreter import (
    Correction,
    DefaultLane,
    FactReading,
    InterpretedStatement,
    InterpretResult,
    NewLane,
    TermLearned,
    TermUnknown,
    TopicReading,
)
from agents.navigator import NavigatorQuestion, NavigatorResult
from extractors.conversation import EXTRACTOR, INTERPRETER, NAVIGATOR
from extractors.errors import ModelUnavailableError, SchemaCallError
from ir.models import NodeOrigin, NodeType
from knowledge.compose import navigator_knowledge
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, Priority, ProgramFact, TopicStatus
from session.candidates import Candidate, rank_candidates
from session.ledger import apply_updates
from session.models import PLACEHOLDER_LANE, LaneStatus, Phase, QuestionKind, Role, Session, StatementOrigin, TurnStatus
from session.orchestrator import (
    FALLBACK_ACK,
    NOT_UPDATED,
    RESEND,
    TurnInput,
    TurnRejected,
    new_session,
    run_close,
    run_turn,
)
from session.patch import (
    AddEdge,
    AddNode,
    EdgeFields,
    GraphPatch,
    NodeFields,
    RemoveNode,
    UpdateEdge,
    UpdateNode,
)
from tests.builders import edge, node, ref
from tests.fakes import FakeConversations
from tests.session_builders import DESCRIPTION, add, first_patch, patch

SUB = "off_label_review"


def reading(**fields: object) -> InterpretResult:
    return InterpretResult(**fields)  # type: ignore[arg-type]


FIRST_READING = reading(
    statements=(
        InterpretedStatement(index=1, topic_ids=("intake.channels",)),
        InterpretedStatement(index=2, topic_ids=("intake.keying",)),
    ),
    topic_updates=(
        TopicReading(topic_id="intake.channels", status="present", statement_refs=(1,)),
        TopicReading(topic_id="intake.keying", status="present", statement_refs=(2,)),
    ),
    new_lanes=(
        NewLane(name="HCP", persona="hcp_office", statement_refs=(1,)),
        NewLane(name="Vendor", persona="external_vendor", description="Keys forms.", statement_refs=(1, 2)),
        NewLane(name="CRM", persona="crm_automation", statement_refs=(2,)),
    ),
)


def says(
    text: str = "Noted.", *questions: NavigatorQuestion, focus: str = MAIN_SCOPE, close: bool = False
) -> NavigatorResult:
    return NavigatorResult(focus=focus, questions=questions, reply=text, propose_close=close)


def ask(candidate_id: str | None, text: str = "And then?", **fields: object) -> NavigatorQuestion:
    return NavigatorQuestion(candidate_id=candidate_id, kind="gap", text=text, **fields)  # type: ignore[arg-type]


def answer(text: str, *topics: tuple[str, str], **fields: object) -> InterpretResult:
    """A one-statement reading of an answer, with the topics it settles."""
    return reading(
        statements=(InterpretedStatement(index=1, raw_text=text),),
        topic_updates=tuple(TopicReading(topic_id=t, status=s, statement_refs=(1,)) for t, s in topics),  # type: ignore[arg-type]
        **fields,
    )


def turn(
    session: Session,
    domain: DomainKnowledge,
    fake: FakeConversations,
    text: str,
    *,
    hint: str | None = None,
    item_key: str | None = None,
) -> Session:
    return run_turn(
        session,
        domain,
        TurnInput(message=text, hint=hint, item_key=item_key),
        conversations=fake,
        max_attempts=2,
    )


def started(domain: DomainKnowledge, fake: FakeConversations) -> Session:
    """A session after its first turn: three lanes learned, five nodes, one open outcome."""
    fake.interpreter(FIRST_READING).extractor(first_patch()).navigator(says("Got it.", ask("c1", "What if not?")))
    return run_turn(
        new_session("test", domain), domain, TurnInput(description=DESCRIPTION), conversations=fake, max_attempts=2
    )


def status(session: Session, topic_id: str) -> TopicStatus:
    entry = session.entry(topic_id)
    assert entry is not None
    return entry.status


# ── turn 1 ───────────────────────────────────────────────────────────────────


def test_the_first_turn_splits_the_description_and_cites_it(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())

    assert [s.id for s in session.corpus] == ["s_0001", "s_0002", "s_0003"]
    assert {s.origin for s in session.corpus} == {StatementOrigin.INITIAL_DESCRIPTION}
    assert session.corpus[0].raw_text == "The HCP faxes the enrollment form to the vendor."
    assert session.corpus[0].topic_ids == ("intake.channels",)
    assert all(n.evidence for n in session.graph.nodes if n.origin is NodeOrigin.SOURCE)


def test_the_first_turn_learns_lanes_and_retires_the_placeholder(domain: DomainKnowledge) -> None:
    """A lane in the automation persona is the system unattributed work was waiting for."""
    session = started(domain, FakeConversations())

    assert [lane.name for lane in session.lanes] == ["HCP", "Vendor", "CRM"]
    assert session.default_lane == "CRM"
    assert session.lane("Vendor").description == "Keys forms."  # type: ignore[union-attr]
    assert session.lane("Vendor").evidence == ("s_0001", "s_0002")  # type: ignore[union-attr]


def test_the_first_turn_leaves_a_valid_graph_a_reply_and_a_pending_question(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())

    assert (session.turn, session.phase, session.turn_status) == (1, Phase.PROBING, TurnStatus.IDLE)
    assert len(session.graph.nodes) == 5
    assert [m.role for m in session.transcript] == [Role.USER, Role.ASSISTANT]
    assert session.transcript[1].text == "Got it."
    assert [q.id for q in session.pending] == ["q_0001"]
    assert session.versions[0].updated and session.versions[0].patch == first_patch()


def test_topics_the_description_covers_are_linked_to_the_steps_that_cite_them(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())

    assert status(session, "intake.keying") is TopicStatus.PRESENT
    assert session.entry("intake.keying").node_ids == ("key_form",)  # type: ignore[union-attr]


def test_a_question_takes_its_subject_from_the_candidate_not_from_the_navigator(domain: DomainKnowledge) -> None:
    """The navigator words it; code decides what it is about, so an answer cannot land on the wrong step."""
    session = started(domain, FakeConversations())
    question = session.pending[0]

    assert (question.kind, question.text) == (QuestionKind.STRUCTURAL, "What if not?")
    assert question.node_ids == ("end_incomplete", "gw_complete")


def test_each_agent_is_shown_only_what_it_is_allowed_to_see(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    started(domain, fake)

    assert fake.cached[NAVIGATOR] == [navigator_knowledge(domain)]
    assert fake.cached[EXTRACTOR] == [None] and fake.cached[INTERPRETER] == [None]
    topic = domain.topic("intake.channels")
    assert topic is not None
    assert topic.ask not in fake.system_prompts[EXTRACTOR][0] + fake.prompts[EXTRACTOR][0]
    assert "[1] The HCP faxes the enrollment form to the vendor." in fake.prompts[INTERPRETER][0]


def test_every_step_of_a_turn_is_timed(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())

    assert [timing.step for timing in session.versions[0].timings] == ["interpreter", "extractor", "navigator"]


def test_an_empty_description_is_rejected_before_any_model_call(domain: DomainKnowledge) -> None:
    fake = FakeConversations()

    with pytest.raises(TurnRejected):
        run_turn(new_session("t", domain), domain, TurnInput(description="  \n "), conversations=fake, max_attempts=2)

    assert fake.calls(INTERPRETER) == 0


# ── answers ──────────────────────────────────────────────────────────────────


def test_an_answer_adds_a_step_and_closes_the_outcome_it_states(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    text = "The vendor faxes the office asking for what is missing."
    fake.interpreter(
        reading(
            statements=(
                InterpretedStatement(
                    index=1, raw_text=text, question_id="q_0001", topic_ids=("missing_info.detection",)
                ),
            ),
            topic_updates=(TopicReading(topic_id="missing_info.detection", status="present", statement_refs=(1,)),),
        )
    )
    fake.extractor(
        patch(
            add(node("fax_office", actor="Vendor", evidence=(ref("s_0004", "The vendor faxes the office"),))),
            UpdateEdge(
                op="update_edge",
                from_id="gw_complete",
                to_id="end_incomplete",
                order=1,
                fields=EdgeFields(to_id="fax_office", evidence=(ref("s_0004", "what is missing"),)),
            ),
            add(edge("fax_office", "end_incomplete")),
        )
    ).navigator(says())

    session = turn(session, domain, fake, text)

    assert session.corpus[-1].origin is StatementOrigin.ANSWER
    assert (session.corpus[-1].turn, session.corpus[-1].question_id) == (2, "q_0001")
    assert [n.id for n in session.graph.nodes][2:4] == ["gw_complete", "fax_office"], "placed where the flow reaches it"
    assert session.entry("missing_info.detection").node_ids == ("fax_office",)  # type: ignore[union-attr]
    assert "s_0004 [NEW; answer, turn 2]" in fake.prompts[EXTRACTOR][-1]


def test_not_sure_defers_the_topic_and_does_not_call_the_extractor(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("Not sure yet", ("consent.validity", "deferred"))).navigator(says())

    session = turn(session, domain, fake, "Not sure yet", hint="The user does not know yet.")

    assert status(session, "consent.validity") is TopicStatus.DEFERRED
    assert fake.calls(EXTRACTOR) == 1, "a quick reply describes no process, so there is nothing to extract"
    assert "The user does not know yet." in fake.prompts[INTERPRETER][-1]
    assert session.transcript[-2].text == "Not sure yet"


def test_we_dont_do_that_marks_the_topic_confirmed_absent(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("We don't send anything.", ("welcome.materials", "confirmed_absent")))
    fake.extractor(patch()).navigator(says())

    session = turn(session, domain, fake, "We don't send anything.")

    assert status(session, "welcome.materials") is TopicStatus.CONFIRMED_ABSENT
    assert len(session.graph.nodes) == 5, "an empty patch is the right answer when the flow does not change"


def test_a_correction_removes_a_step_citing_the_statement_that_withdrew_it(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    text = "Actually the vendor does not key anything."
    fake.interpreter(
        reading(
            statements=(InterpretedStatement(index=1, raw_text=text),),
            corrections=(Correction(statement_refs=(1,), description="The vendor does not key the form."),),
        )
    )
    fake.extractor(
        patch(
            RemoveNode(op="remove_node", id="key_form", reason_statement_ids=("s_0004",)),
            add(edge("start", "gw_complete")),
        )
    ).navigator(says())

    session = turn(session, domain, fake, text)

    assert "key_form" not in {n.id for n in session.graph.nodes}
    assert "(s_0004) The vendor does not key the form." in fake.prompts[EXTRACTOR][-1]
    assert session.entry("intake.keying").node_ids == ()  # type: ignore[union-attr]


def test_a_new_lane_is_learned_and_used_in_the_same_turn(domain: DomainKnowledge) -> None:
    """A proposed lane is usable at once: the extractor needs somewhere to put the work."""
    fake = FakeConversations()
    session = started(domain, fake)
    text = "The PSM calls the patient to welcome them."
    fake.interpreter(
        answer(
            text,
            ("welcome.call", "present"),
            new_lanes=(NewLane(name="PSM", persona="hub_case_owner", statement_refs=(1,)),),
        )
    )
    fake.extractor(
        patch(
            add(node("welcome_call", actor="PSM", evidence=(ref("s_0004", "The PSM calls the patient"),))),
            add(node("end_welcomed", NodeType.TERMINAL, actor="PSM", evidence=(ref("s_0004", "welcome them"),))),
            UpdateNode(op="update_node", id="end_enrolled", fields=NodeFields(type=NodeType.TASK)),
            add(edge("end_enrolled", "welcome_call")),
            add(edge("welcome_call", "end_welcomed")),
        )
    ).navigator(says())

    session = turn(session, domain, fake, text)

    assert session.lane("PSM").persona == "hub_case_owner"  # type: ignore[union-attr]
    assert next(n for n in session.graph.nodes if n.id == "welcome_call").actor == "PSM"
    assert "**PSM**" in fake.system_prompts[EXTRACTOR][-1]


def test_a_lane_the_session_has_not_learned_is_refused_and_repaired(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    invented = patch(
        add(node("call", actor="Nurse", evidence=(ref("s_0004", "Someone calls"),))), add(edge("key_form", "call"))
    )
    fake.interpreter(answer("Someone calls.")).extractor(invented, patch()).navigator(says())

    session = turn(session, domain, fake, "Someone calls.")

    assert "unknown_lane" in fake.prompts[EXTRACTOR][-1]
    assert session.versions[-1].attempts == 2


def test_a_screening_answer_switches_its_dependent_topics_off(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(
        reading(
            statements=(InterpretedStatement(index=1, raw_text="No nurses."),),
            facts=(FactReading(fact=ProgramFact.HAS_NURSE_PROGRAM, value=False, statement_refs=(1,)),),
        )
    )
    fake.extractor(patch()).navigator(says())

    session = turn(session, domain, fake, "No nurses.")

    assert session.facts[ProgramFact.HAS_NURSE_PROGRAM] is False
    assert status(session, "program.nurse") is TopicStatus.CONFIRMED_ABSENT, (
        "the screening topic is settled by its fact"
    )
    assert {status(session, t) for t in ("nurse.offer", "nurse.order", "nurse.timing")} == {TopicStatus.NOT_APPLICABLE}
    assert session.facts[ProgramFact.HAS_REMS] is None


def test_a_question_nobody_answered_goes_back_and_is_not_asked_a_third_time(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    for _ in range(2):
        channels = next(c for c in _candidates(session, domain) if c.topic_ids == ("consent.types",))
        fake.interpreter(answer("Something else entirely.")).extractor(patch()).navigator(says("Ok.", ask(channels.id)))
        session = turn(session, domain, fake, "Something else entirely.")
        assert status(session, "consent.types") is TopicStatus.ASKED

    fake.interpreter(answer("Still something else.")).extractor(patch())
    again = next(c for c in _candidates(session, domain) if c.topic_ids == ("consent.types",))
    fake.navigator(says("Ok.", ask(again.id)))
    session = turn(session, domain, fake, "Still something else.")

    assert session.entry("consent.types").asked_count == 2  # type: ignore[union-attr]
    assert "consent.types" not in {t for q in session.pending for t in q.topic_ids}


def _candidates(session: Session, domain: DomainKnowledge) -> list[Candidate]:
    """The candidates the next turn will rank, once its unanswered questions have fallen back."""
    settled = session.model_copy(deep=True)
    settled.ledger = apply_updates(settled.ledger, [], settled.pending)
    return rank_candidates(settled, domain)


# ── lanes and terms ──────────────────────────────────────────────────────────


def test_steps_in_the_placeholder_lane_move_when_the_user_names_the_system(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    automatic = "A record is created automatically."
    fake.interpreter(reading(new_lanes=(NewLane(name="HCP", persona="hcp_office"),)))
    fake.extractor(
        patch(
            add(node("start", NodeType.START, actor="HCP", evidence=(ref("s_0001", "A record is created"),))),
            add(node("end", NodeType.TERMINAL, actor=PLACEHOLDER_LANE, evidence=(ref("s_0001", "automatically"),))),
            add(edge("start", "end")),
        )
    ).navigator(says("Ok.", ask("c1", "Which system is that?")))
    session = run_turn(
        new_session("t", domain), domain, TurnInput(description=automatic), conversations=fake, max_attempts=2
    )

    assert session.default_lane == PLACEHOLDER_LANE
    assert (session.pending[0].kind, session.pending[0].subject) == (QuestionKind.LANE, PLACEHOLDER_LANE)

    fake.interpreter(
        reading(
            statements=(InterpretedStatement(index=1, raw_text="That's Salesforce."),),
            default_lane=DefaultLane(name="Salesforce", statement_refs=(1,)),
        )
    )
    fake.extractor(patch()).navigator(says())
    session = turn(session, domain, fake, "That's Salesforce.")

    assert session.default_lane == "Salesforce"
    assert [lane.name for lane in session.lanes] == ["HCP", "Salesforce"]
    assert session.lane("Salesforce").status is LaneStatus.CONFIRMED  # type: ignore[union-attr]
    assert next(n for n in session.graph.nodes if n.id == "end").actor == "Salesforce"


def test_an_unknown_term_is_asked_about_and_forgotten_once_explained(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("We send a TTX.", unknown_terms=(TermUnknown(term="TTX", statement_ref=1),)))
    fake.extractor(patch()).navigator(says())
    session = turn(session, domain, fake, "We send a TTX.")
    assert [(t.term, t.first_statement_id) for t in session.unknown_terms] == [("TTX", "s_0004")]

    fake.interpreter(
        answer("TTX is our reminder text.", learned_terms=(TermLearned(term="TTX", meaning="a reminder text"),))
    )
    fake.extractor(patch()).navigator(says())
    session = turn(session, domain, fake, "TTX is our reminder text.")

    assert session.unknown_terms == []
    assert "**TTX**: a reminder text" in fake.system_prompts[EXTRACTOR][-1]


def test_a_glossary_term_or_a_lane_is_never_an_unknown_term(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(
        answer(
            "PEF, vendor.",
            unknown_terms=(TermUnknown(term="PEF", statement_ref=1), TermUnknown(term="vendor", statement_ref=1)),
        )
    )
    fake.extractor(patch()).navigator(says())

    assert turn(session, domain, fake, "PEF, vendor.").unknown_terms == []


def test_a_statement_that_is_not_the_users_own_words_is_replaced_by_the_message(domain: DomainKnowledge) -> None:
    """Statement text is what quotes are checked against, so it cannot be something the model wrote."""
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(
        reading(
            statements=(
                InterpretedStatement(
                    index=1, raw_text="An e-sign link is sent by the CRM", restatement="Consent is sent."
                ),
            )
        )
    )
    fake.extractor(patch()).navigator(says())

    session = turn(session, domain, fake, "Yeah, we send a link.")

    assert session.corpus[-1].raw_text == "Yeah, we send a link."
    assert session.corpus[-1].restatement == "Consent is sent."


# ── focus ────────────────────────────────────────────────────────────────────


def test_focus_moves_into_a_subprocess_when_an_answer_is_about_it_and_back_when_it_is_settled(
    domain: DomainKnowledge,
) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    text = "If it is off-label the vendor reviews the diagnosis."
    fake.interpreter(
        reading(
            statements=(InterpretedStatement(index=1, raw_text=text, scope=SUB),),
            topic_updates=(
                TopicReading(topic_id="eligibility.off_label_detection", status="present", statement_refs=(1,)),
            ),
        )
    )
    fake.extractor(patch()).navigator(says(focus=SUB))

    session = turn(session, domain, fake, text)

    assert session.focus == SUB
    assert session.corpus[-1].scope == SUB

    fake.interpreter(
        answer(
            "They call the prescriber; off-label patients are closed.",
            ("off_label_review.clarification", "present"),
            ("off_label_review.outcome", "present"),
        )
    )
    fake.extractor(patch()).navigator(says(focus=SUB))

    session = turn(session, domain, fake, "They call the prescriber; off-label patients are closed.")

    assert session.focus == MAIN_SCOPE, "its high-priority topics are settled, so the conversation returns"


def test_the_navigator_cannot_move_focus_into_a_subprocess_nobody_has_mentioned(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(says(focus="duplicate_handling"))

    assert turn(session, domain, fake, "Ok.").focus == MAIN_SCOPE


def test_a_scope_the_user_opens_is_honoured_on_the_next_turn(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    session.requested_focus = "missing_info_hcp"
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(says(focus=MAIN_SCOPE))

    session = turn(session, domain, fake, "Ok.")

    assert session.focus == "missing_info_hcp"
    assert session.requested_focus is None
    assert "Focus: missing_info_hcp" in fake.prompts[NAVIGATOR][-1]


# ── failures ─────────────────────────────────────────────────────────────────


def test_when_extraction_runs_out_of_attempts_the_graph_is_kept_and_the_statements_are_retried(
    domain: DomainKnowledge,
) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    before = session.graph
    bad = patch(add(node("orphan", actor="Vendor")))
    fake.interpreter(answer("The vendor archives it.")).extractor(bad, bad).navigator(says("Kept."))

    session = turn(session, domain, fake, "The vendor archives it.")

    assert session.graph == before
    assert not session.flow_updated
    assert session.retry_statement_ids == ["s_0004"]
    assert session.versions[-1].structural, "the last attempt's defects are kept for diagnosis"
    assert "The flow was not updated this turn" in fake.prompts[NAVIGATOR][-1]

    fake.interpreter(answer("Nothing more.", ("consent.types", "deferred")))
    fake.extractor(
        patch(
            add(node("archive", actor="Vendor", evidence=(ref("s_0004", "The vendor archives it"),))),
            UpdateEdge(
                op="update_edge",
                from_id="gw_complete",
                to_id="end_incomplete",
                order=1,
                fields=EdgeFields(to_id="archive", evidence=(ref("s_0004", "archives it"),)),
            ),
            add(edge("archive", "end_incomplete")),
        )
    ).navigator(says())

    session = turn(session, domain, fake, "Nothing more.")

    assert "s_0004 [RETRY; answer, turn 2]" in fake.prompts[EXTRACTOR][-1]
    assert "archive" in {n.id for n in session.graph.nodes}
    assert session.retry_statement_ids == [] and session.flow_updated


def test_if_the_interpreter_cannot_answer_the_turn_is_rejected_and_nothing_changes(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    snapshot = session.model_dump_json()
    fake.interpreter(SchemaCallError("bad"), SchemaCallError("still bad"))

    with pytest.raises(TurnRejected, match="send it again") as rejected:
        turn(session, domain, fake, "An answer.")

    assert str(rejected.value) == RESEND
    assert session.model_dump_json() == snapshot
    assert fake.calls(EXTRACTOR) == 1 and fake.calls(NAVIGATOR) == 1


def test_the_interpreter_gets_one_repair_turn_for_a_schema_slip(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(SchemaCallError("statements.0.index: missing"), answer("Ok.")).extractor(patch()).navigator(says())

    session = turn(session, domain, fake, "Ok.")

    assert session.turn == 2
    assert "statements.0.index: missing" in fake.prompts[INTERPRETER][-1]


@pytest.mark.parametrize("role", [INTERPRETER, EXTRACTOR, NAVIGATOR])
def test_a_request_the_api_refuses_aborts_the_turn_with_no_state_change(domain: DomainKnowledge, role: str) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    snapshot = session.model_dump_json()
    refusal = ModelUnavailableError("the API rejected the request: invalid x-api-key")
    fake.interpreter(refusal if role == INTERPRETER else answer("The vendor archives it."))
    fake.extractor(refusal if role == EXTRACTOR else patch())
    fake.navigator(refusal if role == NAVIGATOR else says())

    with pytest.raises(TurnRejected, match="invalid x-api-key"):
        turn(session, domain, fake, "The vendor archives it.")

    assert session.model_dump_json() == snapshot


def test_if_the_navigator_cannot_answer_the_reply_falls_back_to_the_top_candidates_question(
    domain: DomainKnowledge,
) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(SchemaCallError("no reply"))

    session = turn(session, domain, fake, "Ok.")

    assert session.transcript[-1].text == FALLBACK_ACK
    assert session.pending[0].text == "At the decision 'Gw Complete', what happens when: the form is not complete?"
    assert session.pending[0].kind is QuestionKind.STRUCTURAL


def test_the_fallback_reply_says_so_when_the_flow_was_not_updated(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    bad = patch(add(node("orphan", actor="Vendor")))
    fake.interpreter(answer("The vendor archives it.")).extractor(bad, bad).navigator(SchemaCallError("no reply"))

    session = turn(session, domain, fake, "The vendor archives it.")

    assert session.transcript[-1].text == f"{FALLBACK_ACK} {NOT_UPDATED}"


# ── questions ────────────────────────────────────────────────────────────────


def test_at_most_three_questions_are_asked_and_a_suggested_one_keeps_only_real_ids(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("Ok.")).extractor(patch())
    fake.navigator(
        says(
            "Ok.",
            ask("c1"),
            ask("c2"),
            ask(None, "Anything about shipping?", topic_ids=("no.such.topic", "consent.gate"), node_ids=("ghost",)),
            ask("c3"),
        )
    )

    session = turn(session, domain, fake, "Ok.")

    assert len(session.pending) == 3
    suggested = session.pending[2]
    assert (suggested.kind, suggested.topic_ids, suggested.node_ids) == (QuestionKind.SUGGESTED, ("consent.gate",), ())
    assert [q.id for q in session.pending] == ["q_0002", "q_0003", "q_0004"]


def test_asking_about_a_topic_marks_it_asked(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())
    fake = FakeConversations()
    candidate = next(c for c in _candidates(session, domain) if c.topic_ids == ("consent.types",))
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(says("Ok.", ask(candidate.id, "Which consents?")))

    session = turn(session, domain, fake, "Ok.")

    assert status(session, "consent.types") is TopicStatus.ASKED


# ── closing ──────────────────────────────────────────────────────────────────


def test_saying_done_moves_the_session_to_closing_and_asks_nothing_more(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(reading(statements=(InterpretedStatement(index=1, raw_text="That's everything."),), meta="done"))
    fake.navigator(says("Here is what is open.", ask("c1")))

    session = turn(session, domain, fake, "That's everything.")

    assert session.phase is Phase.CLOSING
    assert session.pending == []
    assert fake.calls(EXTRACTOR) == 1, "saying you are finished describes no process"
    assert "The session is closing" in fake.prompts[NAVIGATOR][-1]
    assert "What happens when the form is not complete is not stated." in fake.prompts[NAVIGATOR][-1]


def test_closing_lists_what_is_open_and_falls_back_to_code_if_the_navigator_cannot(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.navigator(SchemaCallError("no reply"))

    closed = run_close(session, domain, conversations=fake)

    assert closed.phase is Phase.CLOSING and closed.pending == []
    assert session.phase is Phase.PROBING, "the session given is never modified"
    assert "Here is what is still open:" in closed.transcript[-1].text
    assert "Main flow:" in closed.transcript[-1].text


def test_answering_at_close_out_reopens_the_conversation_about_that_item(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = run_close(started(domain, fake), domain, conversations=fake.navigator(says("Open items.")))
    fake.interpreter(answer("It is returned to the office.")).extractor(patch()).navigator(says())

    session = turn(session, domain, fake, "It is returned to the office.", item_key="node:end_incomplete")

    assert session.phase is Phase.PROBING
    assert "steps: End Incomplete (end_incomplete)" in fake.prompts[INTERPRETER][-1]


def test_the_navigator_may_propose_closing_only_when_nothing_important_is_left(domain: DomainKnowledge) -> None:
    fake = FakeConversations()
    session = started(domain, fake)
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(says(close=True))
    assert turn(session, domain, fake, "Ok.").phase is Phase.PROBING

    for fact in ProgramFact:
        session.facts[fact] = True
    session.ledger = [
        e.model_copy(update={"status": TopicStatus.PRESENT}) if e.priority is not Priority.LOW else e
        for e in session.ledger
    ]
    session.accepted_open_items.append("node:end_incomplete")
    fake.interpreter(answer("Ok.")).extractor(patch()).navigator(says(close=True))

    assert turn(session, domain, fake, "Ok.").phase is Phase.CLOSING


def test_a_patch_type_is_not_needed_to_read_a_version(domain: DomainKnowledge) -> None:
    session = started(domain, FakeConversations())

    restored = Session.model_validate_json(session.model_dump_json())

    assert isinstance(restored.versions[0].patch, GraphPatch)
    assert isinstance(restored.versions[0].patch.operations[0], AddNode)
    assert isinstance(restored.versions[0].patch.operations[-1], AddEdge)
