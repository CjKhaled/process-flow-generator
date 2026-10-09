"""The turn pipeline: what happens between one message and the next reply."""

from knowledge.loader import DomainKnowledge
from session.ledger import initial_ledger
from session.models import LaneStatus, Session, SessionLane
from session.patch import empty_graph


def new_session(session_id: str, domain: DomainKnowledge) -> Session:
    """A session before anything has been said.

    It starts with one lane: a placeholder for whatever system does the
    program's automated work, standing in the process's default persona. No
    client is chosen, so the session cannot know that system's name -- but
    unattributed work has to go somewhere from the first turn, and a lane whose
    name says it is unconfirmed is honest about that where a guessed name would
    not be.

    Args:
        session_id: The id to give it.
        domain: The knowledge base for the process the session is about.

    Returns:
        The session, with an empty graph and an untouched ledger.
    """
    session = Session(id=session_id, process_id=domain.process.id, graph=empty_graph(domain.process.id))
    session.lanes.append(
        SessionLane(name=session.default_lane, persona=domain.process.default_persona, status=LaneStatus.PLACEHOLDER)
    )
    session.ledger = initial_ledger(domain)
    return session
