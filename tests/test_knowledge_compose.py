"""What each agent is told about the domain.

The rule under test is the project's hardest: domain knowledge drives questions,
never content. So the assertions that matter are about what the extractor's view
does *not* contain.
"""

from knowledge.compose import extractor_context, interpreter_context, lane_description, navigator_knowledge
from knowledge.loader import DomainKnowledge
from knowledge.schemas import ProgramFact, TopicStatus
from session.models import PLACEHOLDER_LANE, LearnedTerm, SessionLane
from session.orchestrator import new_session


def test_the_navigator_reads_every_file_in_full_under_its_path(domain: DomainKnowledge) -> None:
    knowledge = navigator_knowledge(domain)

    for document in domain.documents:
        assert f"# Knowledge file: {document.path}" in knowledge
        assert document.body in knowledge


def test_the_navigator_reads_the_whole_checklist(domain: DomainKnowledge) -> None:
    knowledge = navigator_knowledge(domain)

    for topic in domain.checklist.topics:
        assert topic.id in knowledge
        assert topic.ask in knowledge


def test_the_navigators_knowledge_is_the_same_text_every_time(domain: DomainKnowledge) -> None:
    """It is the cached part of the prompt, so it may not vary between turns or sessions."""
    assert navigator_knowledge(domain) == navigator_knowledge(domain)


def test_the_extractor_sees_no_checklist_and_no_markdown(domain: DomainKnowledge) -> None:
    """Nothing that says what a program usually does may reach the agent that writes the graph."""
    context = extractor_context(domain, new_session("s", domain))

    for topic in domain.checklist.topics:
        assert topic.ask not in context
        assert topic.id not in context
    for document in domain.documents:
        assert document.body[:200] not in context
        assert f"Knowledge file: {document.path}" not in context


def test_the_extractor_is_given_only_the_declared_subprocess_values(domain: DomainKnowledge) -> None:
    context = extractor_context(domain, new_session("s", domain))

    for sub in domain.process.subprocesses:
        assert f"`{sub.id}`" in context


def test_the_extractor_is_told_the_lanes_and_where_unattributed_work_goes(domain: DomainKnowledge) -> None:
    session = new_session("s", domain)
    session.lanes.append(SessionLane(name="PSM", persona="hub_case_owner", description="Owns outreach to the patient."))

    context = extractor_context(domain, session)

    assert "**PSM**" in context
    assert "Owns outreach to the patient." in context
    assert f"use `{PLACEHOLDER_LANE}`" in context


def test_a_lane_is_described_by_its_persona_then_by_what_the_user_said(domain: DomainKnowledge) -> None:
    session = new_session("s", domain)
    session.lanes.append(SessionLane(name="PSM", persona="hub_case_owner", description="Assigned by ZIP."))

    described = lane_description(domain, session, "PSM")

    assert described.startswith(domain.personas["hub_case_owner"].lane_description)
    assert described.endswith("Assigned by ZIP.")


def test_a_term_the_session_learned_reaches_the_extractor(domain: DomainKnowledge) -> None:
    session = new_session("s", domain)
    session.glossary.append(LearnedTerm(term="JCRM", meaning="another name for the CRM"))

    assert "**JCRM**: another name for the CRM" in extractor_context(domain, session)


def test_the_interpreter_sees_topic_cues_but_not_their_questions(domain: DomainKnowledge) -> None:
    context = interpreter_context(domain, new_session("s", domain))
    topic = domain.topic("consent.methods")
    assert topic is not None

    assert "`consent.methods`" in context
    assert topic.cues[0] in context
    assert topic.ask not in context


def test_the_interpreter_is_not_shown_topics_that_are_settled(domain: DomainKnowledge) -> None:
    session = new_session("s", domain)
    session.ledger = [
        entry.model_copy(update={"status": TopicStatus.PRESENT}) if entry.topic_id == "consent.methods" else entry
        for entry in session.ledger
    ]

    assert "`consent.methods`" not in interpreter_context(domain, session)


def test_the_interpreter_is_shown_only_the_facts_still_unknown(domain: DomainKnowledge) -> None:
    session = new_session("s", domain)
    session.facts[ProgramFact.HAS_REMS] = False

    context = interpreter_context(domain, session)

    assert ProgramFact.HAS_REMS.value not in context.split("## Program facts not yet known")[1].split("##")[0]
    assert ProgramFact.HAS_NURSE_PROGRAM.value in context
