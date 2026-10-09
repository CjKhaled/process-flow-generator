"""The patch extractor's repair loop, against a scripted model.

No network and no SDK: the conversation is :class:`tests.fakes.FakeConversations`,
so what is exercised is everything this project owns -- the prompt, the patch
application, both validators and the loop that decides what earns a retry.
"""

import pytest

from agents.extractor import Correction, build_prompt, build_system_prompt, check, extract_patch
from extractors.conversation import EXTRACTOR
from extractors.errors import ModelUnavailableError, SchemaCallError
from extractors.prompt import CONVENTIONS
from ir.models import NodeType
from knowledge.loader import DomainKnowledge
from session.patch import GraphPatch, apply_patch
from tests.builders import node, ref
from tests.fakes import FakeConversations
from tests.session_builders import add, first_patch, patch, session_with
from validators.report import FindingCode


def uncited() -> GraphPatch:
    """A patch that would be fine if its start node said where it came from."""
    operations = list(first_patch().operations)
    operations[0] = add(node("start", NodeType.START, actor="HCP"))
    return patch(*operations)


def test_a_sound_patch_is_accepted_on_the_first_attempt(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    fake = FakeConversations().extractor(first_patch())

    outcome = extract_patch(session, domain, ["s_0001", "s_0002", "s_0003"], conversations=fake, max_attempts=3)

    assert outcome.updated and outcome.attempts == 1
    assert [item.id for item in outcome.graph.nodes][:2] == ["start", "key_form"]
    assert outcome.structural == ()
    assert fake.calls(EXTRACTOR) == 1


def test_the_session_is_not_modified(domain: DomainKnowledge) -> None:
    session = session_with(domain)

    extract_patch(
        session, domain, ["s_0001"], conversations=FakeConversations().extractor(first_patch()), max_attempts=1
    )

    assert session.graph.nodes == ()


def test_an_open_outcome_is_a_finding_and_never_a_retry(domain: DomainKnowledge) -> None:
    """A needs_clarification terminal is this stage's output. Retrying it would invite invention."""
    fake = FakeConversations().extractor(first_patch())

    outcome = extract_patch(session_with(domain), domain, ["s_0003"], conversations=fake, max_attempts=3)

    assert fake.calls(EXTRACTOR) == 1
    assert [finding.code for finding in outcome.resolution] == [FindingCode.NEEDS_CLARIFICATION]


def test_a_subprocess_nobody_has_described_is_not_reported_mid_conversation(domain: DomainKnowledge) -> None:
    """The ledger tracks what has not been reached; the graph's findings should not repeat it every turn."""
    outcome = extract_patch(
        session_with(domain),
        domain,
        ["s_0001"],
        conversations=FakeConversations().extractor(first_patch()),
        max_attempts=1,
    )

    assert FindingCode.MISSING_REQUIRED_SUBPROCESS not in {finding.code for finding in outcome.resolution}


def test_missing_evidence_earns_a_repair_turn_that_names_the_node(domain: DomainKnowledge) -> None:
    fake = FakeConversations().extractor(uncited(), first_patch())

    outcome = extract_patch(session_with(domain), domain, ["s_0001"], conversations=fake, max_attempts=3)

    assert outcome.updated and outcome.attempts == 2
    repair = fake.prompts[EXTRACTOR][1]
    assert FindingCode.MISSING_EVIDENCE in repair and "'start'" in repair
    assert "your previous patch" in repair and "was not applied" in repair


def test_a_repair_is_applied_to_the_original_graph_not_on_top_of_the_rejected_patch(domain: DomainKnowledge) -> None:
    """A rejected patch was never applied, so resending the whole thing must not collide with itself."""
    fake = FakeConversations().extractor(uncited(), first_patch())

    outcome = extract_patch(session_with(domain), domain, ["s_0001"], conversations=fake, max_attempts=3)

    assert outcome.structural == ()
    assert len(outcome.graph.nodes) == 5


def test_a_patch_error_earns_a_repair_turn(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.graph, _ = apply_patch(session.graph, first_patch())
    collides = patch(add(node("key_form", actor="Vendor", evidence=(ref("s_0002", "keys the form"),))))
    fake = FakeConversations().extractor(collides, patch())

    outcome = extract_patch(session, domain, ["s_0002"], conversations=fake, max_attempts=3)

    assert outcome.attempts == 2
    assert FindingCode.PATCH_DUPLICATE_NODE in fake.prompts[EXTRACTOR][1]


def test_an_invented_lane_earns_a_repair_turn(domain: DomainKnowledge) -> None:
    operations = list(first_patch().operations)
    operations[1] = add(node("key_form", actor="Intake Team", evidence=(ref("s_0002", "The vendor keys the form"),)))
    fake = FakeConversations().extractor(patch(*operations), first_patch())

    outcome = extract_patch(session_with(domain), domain, ["s_0002"], conversations=fake, max_attempts=3)

    assert outcome.updated
    assert FindingCode.UNKNOWN_LANE in fake.prompts[EXTRACTOR][1]


def test_a_schema_failure_is_retried_with_the_complaint(domain: DomainKnowledge) -> None:
    fake = FakeConversations().extractor(SchemaCallError("operations.0.op: unknown tag"), first_patch())

    outcome = extract_patch(session_with(domain), domain, ["s_0001"], conversations=fake, max_attempts=3)

    assert outcome.updated and outcome.attempts == 2
    assert "operations.0.op: unknown tag" in fake.prompts[EXTRACTOR][1]


def test_exhausting_the_budget_keeps_the_previous_graph_and_does_not_raise(domain: DomainKnowledge) -> None:
    """A conversation always has last turn's graph to fall back on, so this is an outcome, not an error."""
    session = session_with(domain)
    session.graph, _ = apply_patch(session.graph, first_patch())
    fake = FakeConversations().extractor(*(uncited() for _ in range(3)))

    outcome = extract_patch(session, domain, ["s_0001"], conversations=fake, max_attempts=3)

    assert not outcome.updated and outcome.patch is None
    assert outcome.graph == session.graph
    assert outcome.attempts == 3 and fake.calls(EXTRACTOR) == 3
    assert FindingCode.PATCH_DUPLICATE_NODE in {finding.code for finding in outcome.structural}


def test_a_rejected_request_is_not_retried(domain: DomainKnowledge) -> None:
    """No repair prompt can fix a bad key, so the loop must not spend its budget on one."""
    fake = FakeConversations().extractor(ModelUnavailableError("the API rejected the request"))

    with pytest.raises(ModelUnavailableError):
        extract_patch(session_with(domain), domain, ["s_0001"], conversations=fake, max_attempts=3)

    assert fake.calls(EXTRACTOR) == 1


def test_the_attempt_budget_must_be_positive(domain: DomainKnowledge) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        extract_patch(session_with(domain), domain, [], conversations=FakeConversations(), max_attempts=0)


def test_every_attempt_is_timed(domain: DomainKnowledge) -> None:
    ticks = iter(range(100))
    fake = FakeConversations().extractor(uncited(), first_patch())

    outcome = extract_patch(
        session_with(domain), domain, ["s_0001"], conversations=fake, max_attempts=3, clock=lambda: float(next(ticks))
    )

    assert [(timing.step, timing.attempt, timing.seconds) for timing in outcome.timings] == [
        ("extractor", 1, 1.0),
        ("extractor", 2, 1.0),
    ]


def test_the_system_prompt_reuses_the_extraction_conventions_verbatim(domain: DomainKnowledge) -> None:
    assert CONVENTIONS in build_system_prompt(session_with(domain), domain)


def test_the_system_prompt_carries_no_domain_knowledge(domain: DomainKnowledge) -> None:
    """The rule that does not bend: the agent that writes the graph never reads what programs usually do."""
    prompt = build_system_prompt(session_with(domain), domain)

    assert all(topic.ask not in prompt for topic in domain.checklist.topics)
    assert all(document.body[:200] not in prompt for document in domain.documents)


def test_the_prompt_marks_which_statements_are_new_and_which_are_being_retried(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.retry_statement_ids = ["s_0002"]

    prompt = build_prompt(session, ["s_0003"])

    assert "s_0001 [applied; description]" in prompt
    assert "s_0002 [RETRY; description]" in prompt
    assert "s_0003 [NEW; description]" in prompt


def test_the_prompt_carries_the_graph_and_this_turns_corrections(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.graph, _ = apply_patch(session.graph, first_patch())

    prompt = build_prompt(session, ["s_0003"], [Correction(("s_0003",), "The vendor does not key the form.")])

    assert '"id": "key_form"' in prompt
    assert "(s_0003) The vendor does not key the form." in prompt


def test_check_runs_both_validators(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    broken, _ = apply_patch(session.graph, patch(add(node("lonely", actor="Nobody"))))

    found = {finding.code for finding in check(broken, session, domain).findings}

    assert {FindingCode.START_NODE_COUNT, FindingCode.UNKNOWN_LANE, FindingCode.MISSING_EVIDENCE} <= found
