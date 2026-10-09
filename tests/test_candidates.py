"""What gets asked next, and in what order."""

from ir.models import NodeType
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, ProgramFact, TopicStatus
from session.candidates import TOP, Candidate, rank_candidates
from session.ledger import TopicUpdate, apply_updates, mark_asked, node_key
from session.models import AskedQuestion, Message, QuestionKind, Role, Session, SessionLane, UnknownTerm
from session.patch import apply_patch
from tests.builders import node, ref
from tests.session_builders import add, first_patch, patch, session_with


def with_flow(domain: DomainKnowledge, **kwargs: object) -> Session:
    session = session_with(domain, **kwargs)  # type: ignore[arg-type]
    session.graph, _ = apply_patch(session.graph, first_patch())
    return session


def by_topic(candidates: list[Candidate], topic_id: str) -> Candidate:
    return next(candidate for candidate in candidates if topic_id in candidate.topic_ids)


def settle_screening(session: Session) -> None:
    for fact in ProgramFact:
        session.facts[fact] = True


def test_an_open_outcome_in_the_focus_ranks_first_and_names_its_decision(domain: DomainKnowledge) -> None:
    top = rank_candidates(with_flow(domain), domain)[0]

    assert (top.rank, top.kind, top.id) == (1, QuestionKind.STRUCTURAL, "c1")
    assert top.node_ids == ("end_incomplete", "gw_complete")
    assert top.ask == "At the decision 'Gw Complete', what happens when: the form is not complete?"


def test_alternatives_with_no_rule_are_a_structural_gap(domain: DomainKnowledge) -> None:
    session = with_flow(domain)
    session.graph, _ = apply_patch(
        session.graph,
        patch(
            add(
                node(
                    "archive",
                    actor="Vendor",
                    alternatives=("archived", "not entered"),
                    evidence=(ref("s_0002", "keys"),),
                )
            )
        ),
    )

    gaps = [candidate for candidate in rank_candidates(session, domain) if candidate.rank == 1]

    assert "archived; not entered" in gaps[-1].ask


def test_a_gap_outside_the_focus_is_not_a_structural_candidate(domain: DomainKnowledge) -> None:
    session = with_flow(domain)
    session.focus = "off_label_review"

    assert [c for c in rank_candidates(session, domain) if c.kind is QuestionKind.STRUCTURAL] == []


def test_an_accepted_open_outcome_is_not_asked_about_again(domain: DomainKnowledge) -> None:
    session = with_flow(domain)
    session.accepted_open_items.append(node_key("end_incomplete"))

    assert [c for c in rank_candidates(session, domain) if c.kind is QuestionKind.STRUCTURAL] == []


def test_the_placeholder_lane_is_asked_about_only_while_a_step_sits_in_it(domain: DomainKnowledge) -> None:
    unused = session_with(domain, default=None)
    used = session_with(domain, default=None)
    used.graph, _ = apply_patch(
        used.graph, patch(add(node("create_record", actor=used.default_lane, evidence=(ref("s_0002", "keys"),))))
    )

    assert [c for c in rank_candidates(unused, domain) if c.kind is QuestionKind.LANE] == []
    lane = next(c for c in rank_candidates(used, domain) if c.kind is QuestionKind.LANE)
    assert (lane.rank, lane.subject, lane.node_ids) == (2, used.default_lane, ("create_record",))


def test_a_lane_with_no_known_role_and_an_unexplained_term_rank_second(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.lanes.append(SessionLane(name="QRAL"))
    session.unknown_terms.append(UnknownTerm(term="TTRY", first_statement_id="s_0001"))

    second = [candidate for candidate in rank_candidates(session, domain) if candidate.rank == 2]

    assert [(c.kind, c.subject) for c in second] == [(QuestionKind.LANE, "QRAL"), (QuestionKind.TERM, "TTRY")]


def test_screening_topics_come_before_ordinary_gaps_while_their_fact_is_unknown(domain: DomainKnowledge) -> None:
    session = session_with(domain)

    ranked = rank_candidates(session, domain)

    assert [c.topic_ids[0] for c in ranked if c.rank == 3] == [
        "program.rems",
        "program.nurse",
        "program.self_enrollment",
        "program.pediatric",
    ]
    assert by_topic(ranked, "program.rems").kind is QuestionKind.SCREENING

    session.facts[ProgramFact.HAS_REMS] = False

    assert "program.rems" not in {t for c in rank_candidates(session, domain) for t in c.topic_ids}


def test_ranks_follow_the_documented_order(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    settle_screening(session)
    session.ledger = apply_updates(
        session.ledger, [TopicUpdate("consent.gate", TopicStatus.NEEDS_CLARIFICATION, note="who decides?")], []
    )

    ranked = rank_candidates(session, domain)

    assert by_topic(ranked, "intake.channels").rank == 4  # high, in focus
    assert by_topic(ranked, "consent.gate").rank == 5  # needs clarification, in focus
    assert by_topic(ranked, "intake.channel_paths").rank == 6  # normal, in focus
    assert by_topic(ranked, "record.lead_like_state").rank == 7  # low
    assert [c.rank for c in ranked] == sorted(c.rank for c in ranked)


def test_within_a_rank_topics_keep_checklist_order(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    settle_screening(session)
    order = [topic.id for topic in domain.checklist.topics]

    high = [c.topic_ids[0] for c in rank_candidates(session, domain) if c.rank == 4]

    assert high == sorted(high, key=order.index)
    assert high[0] == "intake.channels"


def test_a_subprocess_nobody_has_mentioned_stays_at_the_bottom(domain: DomainKnowledge) -> None:
    """Its high-priority topics matter only once the conversation has reached it."""
    session = session_with(domain)
    settle_screening(session)
    assert by_topic(rank_candidates(session, domain), "off_label_review.outcome").rank == 7

    session.ledger = apply_updates(
        session.ledger, [TopicUpdate("eligibility.off_label_detection", TopicStatus.PRESENT)], []
    )

    assert by_topic(rank_candidates(session, domain), "off_label_review.outcome").rank == 6


def test_moving_focus_into_a_subprocess_promotes_its_topics(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    settle_screening(session)
    session.focus = "off_label_review"

    ranked = rank_candidates(session, domain)

    assert by_topic(ranked, "off_label_review.outcome").rank == 4
    assert by_topic(ranked, "off_label_review.ambiguous").rank == 6
    assert by_topic(ranked, "intake.channels").rank == 6  # high, but now elsewhere


def test_settled_and_inapplicable_topics_are_not_candidates(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.ledger = apply_updates(
        session.ledger,
        [
            TopicUpdate("intake.channels", TopicStatus.PRESENT),
            TopicUpdate("intake.work_pool", TopicStatus.CONFIRMED_ABSENT),
            TopicUpdate("intake.keying", TopicStatus.DEFERRED),
        ],
        [],
    )

    asked = {topic for candidate in rank_candidates(session, domain) for topic in candidate.topic_ids}

    assert asked.isdisjoint({"intake.channels", "intake.work_pool", "intake.keying"})


def test_a_topic_asked_twice_without_an_answer_becomes_a_skip_offer_and_sinks(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    settle_screening(session)
    question = AskedQuestion(id="q", turn=1, kind=QuestionKind.GAP, topic_ids=("intake.channels",), text="How?")
    for _ in range(2):
        session.ledger = apply_updates(mark_asked(session.ledger, [question]), [], [question])

    ranked = rank_candidates(session, domain)
    channels = by_topic(ranked, "intake.channels")

    assert channels.skip_offer
    assert ranked.index(channels) > TOP
    assert not any(candidate.skip_offer for candidate in ranked[:TOP])


def test_a_step_asked_about_twice_becomes_a_skip_offer(domain: DomainKnowledge) -> None:
    session = with_flow(domain)
    question = AskedQuestion(
        id="q", turn=1, kind=QuestionKind.STRUCTURAL, node_ids=("end_incomplete",), text="What then?"
    )
    session.transcript.extend(Message(role=Role.ASSISTANT, text="…", turn=t, questions=(question,)) for t in (1, 2))

    structural = next(c for c in rank_candidates(session, domain) if c.kind is QuestionKind.STRUCTURAL)

    assert structural.skip_offer


def test_every_candidate_carries_what_the_navigator_needs(domain: DomainKnowledge) -> None:
    channels = by_topic(rank_candidates(session_with(domain), domain), "intake.channels")
    topic = domain.topic("intake.channels")
    assert topic is not None

    assert channels.ask == topic.ask
    assert channels.follow_ups == topic.follow_ups
    assert channels.scope == MAIN_SCOPE
    assert "high-priority" in channels.reason


def test_candidate_ids_are_unique_and_follow_rank_order(domain: DomainKnowledge) -> None:
    ranked = rank_candidates(with_flow(domain), domain)

    assert [candidate.id for candidate in ranked] == [f"c{index}" for index in range(1, len(ranked) + 1)]


def test_a_start_node_is_never_a_candidate(domain: DomainKnowledge) -> None:
    ranked = rank_candidates(with_flow(domain), domain)

    assert all(NodeType.START.value not in candidate.ask for candidate in ranked if candidate.rank == 1)
