"""The coverage ledger: transitions, applicability, linking and completion."""

from ir.models import NodeType
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, ProgramFact, TopicStatus
from session.ledger import (
    TopicUpdate,
    apply_applicability,
    apply_updates,
    coverage,
    initial_ledger,
    ledger_findings,
    link_nodes,
    mark_asked,
    node_key,
    open_items,
    scope_complete,
    topic_key,
)
from session.models import AskedQuestion, LedgerEntry, QuestionKind
from session.patch import apply_patch
from tests.builders import graph, node, ref
from tests.session_builders import first_patch, session_with
from validators.report import FindingCode

NO_FACTS: dict[ProgramFact, bool | None] = dict.fromkeys(ProgramFact)


def question(*topic_ids: str) -> AskedQuestion:
    return AskedQuestion(id="q_0001", turn=1, kind=QuestionKind.GAP, topic_ids=topic_ids, text="How?")


def status(ledger: list[LedgerEntry], topic_id: str) -> TopicStatus:
    return next(entry.status for entry in ledger if entry.topic_id == topic_id)


def entry(ledger: list[LedgerEntry], topic_id: str) -> LedgerEntry:
    return next(item for item in ledger if item.topic_id == topic_id)


def test_asking_a_topic_marks_it_asked_and_counts_it(domain: DomainKnowledge) -> None:
    ledger = mark_asked(initial_ledger(domain), [question("consent.methods")])

    assert status(ledger, "consent.methods") is TopicStatus.ASKED
    assert entry(ledger, "consent.methods").asked_count == 1
    assert status(ledger, "consent.types") is TopicStatus.NOT_YET_COVERED


def test_an_answer_moves_an_asked_topic_to_what_the_user_said(domain: DomainKnowledge) -> None:
    asked = mark_asked(initial_ledger(domain), [question("consent.methods")])

    for answer in (
        TopicStatus.PRESENT,
        TopicStatus.CONFIRMED_ABSENT,
        TopicStatus.NEEDS_CLARIFICATION,
        TopicStatus.DEFERRED,
    ):
        ledger = apply_updates(
            asked, [TopicUpdate("consent.methods", answer, ("s_0004",))], [question("consent.methods")]
        )

        assert status(ledger, "consent.methods") is answer
        assert entry(ledger, "consent.methods").evidence == ("s_0004",)


def test_a_topic_asked_but_not_answered_goes_back_with_its_count_kept(domain: DomainKnowledge) -> None:
    """Silence is not absence -- and the count is what stops a third asking."""
    asked = mark_asked(initial_ledger(domain), [question("consent.methods", "consent.types")])

    ledger = apply_updates(
        asked, [TopicUpdate("consent.types", TopicStatus.PRESENT)], [question("consent.methods", "consent.types")]
    )

    assert status(ledger, "consent.methods") is TopicStatus.NOT_YET_COVERED
    assert entry(ledger, "consent.methods").asked_count == 1


def test_a_topic_mentioned_unprompted_is_recorded(domain: DomainKnowledge) -> None:
    ledger = apply_updates(initial_ledger(domain), [TopicUpdate("welcome.call", TopicStatus.PRESENT, ("s_0002",))], [])

    assert status(ledger, "welcome.call") is TopicStatus.PRESENT


def test_a_topic_needing_clarification_can_be_asked_again_and_falls_back_to_that(domain: DomainKnowledge) -> None:
    unclear = apply_updates(
        initial_ledger(domain), [TopicUpdate("consent.gate", TopicStatus.NEEDS_CLARIFICATION, note="who decides?")], []
    )
    asked = mark_asked(unclear, [question("consent.gate")])

    assert status(asked, "consent.gate") is TopicStatus.ASKED
    assert (
        status(apply_updates(asked, [], [question("consent.gate")]), "consent.gate") is TopicStatus.NEEDS_CLARIFICATION
    )


def test_a_deferred_topic_can_be_answered_later(domain: DomainKnowledge) -> None:
    deferred = apply_updates(initial_ledger(domain), [TopicUpdate("consent.validity", TopicStatus.DEFERRED)], [])

    ledger = apply_updates(deferred, [TopicUpdate("consent.validity", TopicStatus.PRESENT, ("s_0009",))], [])

    assert status(ledger, "consent.validity") is TopicStatus.PRESENT


def test_a_settled_topic_is_not_reopened_by_a_follow_up(domain: DomainKnowledge) -> None:
    present = apply_updates(initial_ledger(domain), [TopicUpdate("consent.methods", TopicStatus.PRESENT)], [])

    assert status(mark_asked(present, [question("consent.methods")]), "consent.methods") is TopicStatus.PRESENT


def test_an_update_cannot_set_a_status_that_belongs_to_code(domain: DomainKnowledge) -> None:
    ledger = apply_updates(initial_ledger(domain), [TopicUpdate("consent.methods", TopicStatus.NOT_APPLICABLE)], [])

    assert status(ledger, "consent.methods") is TopicStatus.NOT_YET_COVERED


def test_evidence_accumulates_across_answers(domain: DomainKnowledge) -> None:
    once = apply_updates(initial_ledger(domain), [TopicUpdate("consent.methods", TopicStatus.PRESENT, ("s_0002",))], [])
    twice = apply_updates(once, [TopicUpdate("consent.methods", TopicStatus.PRESENT, ("s_0002", "s_0007"))], [])

    assert entry(twice, "consent.methods").evidence == ("s_0002", "s_0007")


def test_a_denied_program_fact_switches_its_topics_off(domain: DomainKnowledge) -> None:
    ledger = apply_applicability(initial_ledger(domain), domain, {**NO_FACTS, ProgramFact.HAS_NURSE_PROGRAM: False})

    assert status(ledger, "nurse.offer") is TopicStatus.NOT_APPLICABLE
    assert status(ledger, "welcome.parallel_clinical") is TopicStatus.NOT_APPLICABLE
    assert status(ledger, "rems.requirements") is TopicStatus.NOT_YET_COVERED


def test_an_unknown_or_confirmed_fact_switches_nothing_off(domain: DomainKnowledge) -> None:
    for facts in (NO_FACTS, {**NO_FACTS, ProgramFact.HAS_NURSE_PROGRAM: True}):
        ledger = apply_applicability(initial_ledger(domain), domain, facts)

        assert TopicStatus.NOT_APPLICABLE not in {item.status for item in ledger}


def test_a_corrected_fact_switches_its_topics_back_on(domain: DomainKnowledge) -> None:
    off = apply_applicability(initial_ledger(domain), domain, {**NO_FACTS, ProgramFact.HAS_REMS: False})

    back = apply_applicability(off, domain, {**NO_FACTS, ProgramFact.HAS_REMS: True})

    assert status(back, "rems.requirements") is TopicStatus.NOT_YET_COVERED


def test_a_subprocess_the_user_says_does_not_exist_takes_its_topics_with_it(domain: DomainKnowledge) -> None:
    """Asking about the inside of a review the program does not have would be describing someone else's program."""
    absent = apply_updates(
        initial_ledger(domain), [TopicUpdate("eligibility.off_label_detection", TopicStatus.CONFIRMED_ABSENT)], []
    )

    ledger = apply_applicability(absent, domain, NO_FACTS)

    assert {item.status for item in ledger if item.scope == "off_label_review"} == {TopicStatus.NOT_APPLICABLE}
    assert status(ledger, "duplicate_handling.outcomes") is TopicStatus.NOT_YET_COVERED


def test_a_topic_is_linked_to_the_nodes_that_cite_its_statements(domain: DomainKnowledge) -> None:
    flow = graph(
        nodes=(
            node("send_link", evidence=(ref("s_0004", "send a link"),)),
            node("mail_form", evidence=(ref("s_0005", "mail a paper form"), ref("s_0004", "or"))),
            node("unrelated", evidence=(ref("s_0001", "faxes"),)),
        ),
        edges=(),
    )
    ledger = apply_updates(
        initial_ledger(domain), [TopicUpdate("consent.methods", TopicStatus.PRESENT, ("s_0004",))], []
    )

    assert entry(link_nodes(ledger, flow), "consent.methods").node_ids == ("send_link", "mail_form")


def test_a_covered_topic_with_no_node_is_reported(domain: DomainKnowledge) -> None:
    ledger = apply_updates(
        initial_ledger(domain), [TopicUpdate("consent.methods", TopicStatus.PRESENT, ("s_0004",))], []
    )

    findings = ledger_findings(link_nodes(ledger, graph(nodes=(), edges=())), domain, MAIN_SCOPE)

    assert FindingCode.TOPIC_WITHOUT_NODES in {finding.code for finding in findings}


def test_open_and_deferred_topics_are_reported_but_unreached_minor_ones_are_not(domain: DomainKnowledge) -> None:
    ledger = apply_updates(
        initial_ledger(domain),
        [
            TopicUpdate("consent.validity", TopicStatus.DEFERRED),
            TopicUpdate("consent.verbal", TopicStatus.NEEDS_CLARIFICATION, note="which states?"),
        ],
        [],
    )

    findings = ledger_findings(ledger, domain, MAIN_SCOPE)
    messages = " | ".join(finding.message for finding in findings)

    assert "'Consent validity period' was put off" in messages
    assert "'Verbal consent' still needs clarifying: which states?" in messages
    assert "'Intake channels' was not covered" in messages  # high priority, never reached
    assert "Receipt acknowledged" not in messages  # normal priority, never reached
    assert {finding.code for finding in findings} == {FindingCode.OPEN_TOPIC, FindingCode.DEFERRED_TOPIC}


def test_findings_can_be_restricted_to_one_scope(domain: DomainKnowledge) -> None:
    findings = ledger_findings(initial_ledger(domain), domain, "off_label_review")

    assert {finding.message for finding in findings} == {
        "'Clarifying with the prescriber' was not covered",
        "'Off-label outcome' was not covered",
    }


def test_a_scope_is_complete_when_its_required_topics_are_accepted(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    assert not scope_complete(session, domain, "off_label_review")

    session.ledger = apply_updates(
        session.ledger,
        [
            TopicUpdate("off_label_review.clarification", TopicStatus.DEFERRED),
            TopicUpdate("off_label_review.outcome", TopicStatus.CONFIRMED_ABSENT),
        ],
        [],
    )

    assert scope_complete(session, domain, "off_label_review")
    assert not scope_complete(session, domain, MAIN_SCOPE)


def test_a_rule_terminal_holds_its_scope_open_until_the_user_accepts_it(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.graph, _ = apply_patch(session.graph, first_patch())
    session.ledger = [
        item.model_copy(update={"status": TopicStatus.PRESENT}) if item.scope == MAIN_SCOPE else item
        for item in session.ledger
    ]
    assert not scope_complete(session, domain, MAIN_SCOPE)

    session.accepted_open_items.append(node_key("end_incomplete"))

    assert scope_complete(session, domain, MAIN_SCOPE)


def test_open_items_list_open_steps_and_topics_until_they_are_accepted(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.graph, _ = apply_patch(session.graph, first_patch())
    session.ledger = apply_updates(session.ledger, [TopicUpdate("consent.validity", TopicStatus.DEFERRED)], [])

    items = {item.key: item for item in open_items(session, domain)}

    assert items[node_key("end_incomplete")].kind == "step"
    assert "not stated" in items[node_key("end_incomplete")].text
    assert items[topic_key("consent.validity")].text == "Consent validity period (to check later)"

    session.accepted_open_items.extend(items)

    assert open_items(session, domain) == ()


def test_coverage_counts_by_status_and_lists_what_is_open_per_scope(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.ledger = apply_updates(session.ledger, [TopicUpdate("off_label_review.outcome", TopicStatus.PRESENT)], [])

    summary = {scope["scope"]: scope for scope in coverage(session, domain)}

    assert list(summary) == list(domain.process.scopes)
    assert summary["off_label_review"]["label"] == "Off-label review"
    assert summary["off_label_review"]["counts"] == {"not_yet_covered": 6, "present": 1}
    assert summary[MAIN_SCOPE]["label"] == "Main flow"
    assert not summary[MAIN_SCOPE]["complete"]


def test_an_annotation_counts_as_a_step_for_linking(domain: DomainKnowledge) -> None:
    flow = graph(nodes=(node("note", NodeType.ANNOTATION, evidence=(ref("s_0008", "valid for a year"),)),), edges=())
    ledger = apply_updates(
        initial_ledger(domain), [TopicUpdate("consent.validity", TopicStatus.PRESENT, ("s_0008",))], []
    )

    assert entry(link_nodes(ledger, flow), "consent.validity").node_ids == ("note",)
