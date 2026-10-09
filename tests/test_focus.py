"""Where the conversation is focused, and who may move it."""

from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, Priority, ProgramFact, TopicStatus
from session.candidates import rank_candidates
from session.focus import accept_focus, entering_focus, settled, valid_scope
from session.ledger import TopicUpdate, apply_updates
from session.models import Session
from tests.session_builders import session_with

SUB = "off_label_review"


def reach(session: Session) -> None:
    """The user has described the decision that hands off to off-label review."""
    session.ledger = apply_updates(
        session.ledger, [TopicUpdate("eligibility.off_label_detection", TopicStatus.PRESENT)], []
    )


def settle_high(session: Session, scope: str) -> None:
    session.ledger = [
        entry.model_copy(update={"status": TopicStatus.PRESENT})
        if entry.scope == scope and entry.priority is Priority.HIGH
        else entry
        for entry in session.ledger
    ]


def decide(session: Session, domain: DomainKnowledge, proposed: str | None, **kwargs: object) -> str:
    return accept_focus(proposed, session, domain, rank_candidates(session, domain), **kwargs)  # type: ignore[arg-type]


def test_focus_starts_on_the_main_flow(domain: DomainKnowledge) -> None:
    assert session_with(domain).focus == MAIN_SCOPE


def test_only_the_processs_own_scopes_are_valid(domain: DomainKnowledge) -> None:
    assert valid_scope(domain, MAIN_SCOPE) and valid_scope(domain, SUB)
    assert not valid_scope(domain, "onboarding") and not valid_scope(domain, None)


def test_a_user_request_always_wins(domain: DomainKnowledge) -> None:
    session = session_with(domain)

    assert decide(session, domain, MAIN_SCOPE, requested=SUB) == SUB
    assert decide(session, domain, None, requested="duplicate_handling") == "duplicate_handling"


def test_a_proposal_that_is_not_a_scope_is_ignored(domain: DomainKnowledge) -> None:
    assert decide(session_with(domain), domain, "onboarding") == MAIN_SCOPE
    assert decide(session_with(domain), domain, None) == MAIN_SCOPE


def test_a_subprocess_nobody_has_reached_cannot_take_the_focus(domain: DomainKnowledge) -> None:
    """The navigator knows such a review usually exists. That is not a reason to discuss it."""
    assert decide(session_with(domain), domain, SUB) == MAIN_SCOPE


def test_a_reached_subprocess_waits_while_the_main_flow_has_more_pressing_gaps(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    reach(session)

    assert decide(session, domain, SUB) == MAIN_SCOPE


def test_focus_moves_in_once_the_main_flow_has_only_lesser_gaps_left(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    reach(session)
    for fact in ProgramFact:
        session.facts[fact] = True
    settle_high(session, MAIN_SCOPE)

    assert decide(session, domain, SUB) == SUB


def test_an_answer_about_a_subprocess_moves_the_focus_there(domain: DomainKnowledge) -> None:
    session = session_with(domain)

    assert decide(session, domain, SUB, scopes_raised_this_turn={SUB}) == SUB


def test_focus_does_not_leave_a_subprocess_that_is_not_settled(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.focus = SUB

    assert decide(session, domain, MAIN_SCOPE) == SUB


def test_focus_returns_to_main_once_the_subprocess_is_settled(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.focus = SUB
    settle_high(session, SUB)

    assert settled(session, SUB)
    assert decide(session, domain, MAIN_SCOPE) == MAIN_SCOPE
    assert entering_focus(session, domain) == MAIN_SCOPE, "it returns without waiting for the navigator to propose it"


def test_a_turn_starts_from_the_scope_the_user_opened_in_the_page(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    session.requested_focus = "missing_info_hcp"

    assert entering_focus(session, domain) == "missing_info_hcp"


def test_a_settled_subprocess_is_not_entered_again(domain: DomainKnowledge) -> None:
    session = session_with(domain)
    reach(session)
    settle_high(session, MAIN_SCOPE)
    settle_high(session, SUB)

    assert decide(session, domain, SUB) == MAIN_SCOPE
