"""The session file: what a conversation is, on disk."""

from knowledge.loader import DomainKnowledge
from knowledge.schemas import ProgramFact, TopicStatus
from session.models import (
    PLACEHOLDER_LANE,
    SCHEMA_VERSION,
    LaneStatus,
    Phase,
    Session,
    Statement,
    StatementOrigin,
    TurnStatus,
)
from session.orchestrator import new_session


def test_a_new_session_has_one_placeholder_lane_in_the_default_persona(domain: DomainKnowledge) -> None:
    session = new_session("abc", domain)

    assert [lane.name for lane in session.lanes] == [PLACEHOLDER_LANE]
    assert session.lanes[0].status is LaneStatus.PLACEHOLDER
    assert session.lanes[0].persona == domain.process.default_persona
    assert session.default_lane == PLACEHOLDER_LANE


def test_a_new_session_knows_no_program_facts(domain: DomainKnowledge) -> None:
    assert new_session("abc", domain).facts == dict.fromkeys(ProgramFact)


def test_a_new_session_has_an_untouched_entry_for_every_topic(domain: DomainKnowledge) -> None:
    session = new_session("abc", domain)

    assert [entry.topic_id for entry in session.ledger] == [topic.id for topic in domain.checklist.topics]
    assert {entry.status for entry in session.ledger} == {TopicStatus.NOT_YET_COVERED}


def test_a_new_session_starts_describing_on_the_main_flow_with_an_empty_graph(domain: DomainKnowledge) -> None:
    session = new_session("abc", domain)

    assert (session.phase, session.focus, session.turn, session.turn_status) == (
        Phase.DESCRIBING,
        "main",
        0,
        TurnStatus.IDLE,
    )
    assert session.graph.nodes == () and session.graph.edges == ()


def test_a_session_round_trips_through_json(domain: DomainKnowledge) -> None:
    """The file is the single source of truth, so nothing may be lost writing it."""
    session = new_session("abc", domain)
    session.corpus.append(
        Statement(id="s_0001", origin=StatementOrigin.INITIAL_DESCRIPTION, turn=1, raw_text="The HCP faxes a form.")
    )
    session.facts[ProgramFact.HAS_REMS] = False

    restored = Session.model_validate_json(session.model_dump_json())

    assert restored == session
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.facts[ProgramFact.HAS_REMS] is False
