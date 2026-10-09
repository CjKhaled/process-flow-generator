"""Where the conversation is focused, and who gets to move it.

Focus is ``main`` or a subprocess id. It decides which gaps rank highest and
what the page says is being discussed. The navigator *proposes* a focus; this
module decides whether to accept it. The rules are small, and they are code
because a conversation that wanders into a subprocess the user never mentioned,
or never comes back out of one, is the kind of failure nobody notices until the
session is useless.

* It starts on ``main``.
* It moves into a subprocess when the user asks; when an answer this turn was
  about that subprocess; or when the main flow has reached it and what is left on
  the main flow matters less than what is open inside it.
* It returns to ``main`` when the subprocess's high-priority topics are settled
  and no outcome in it is still open, or when the user redirects.
"""

from collections.abc import Collection

from ir.models import NodeStatus
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, Priority
from session.candidates import Candidate, raised, scope_of
from session.ledger import OPEN_STATUSES, node_key
from session.models import Session


def valid_scope(domain: DomainKnowledge, scope: str | None) -> bool:
    """Whether a name is a scope of this process."""
    return scope is not None and scope in domain.process.scopes


def settled(session: Session, scope: str) -> bool:
    """Whether a scope has nothing pressing left: no open high-priority topic, no open outcome."""
    if any(
        entry.scope == scope and entry.priority is Priority.HIGH and entry.status in OPEN_STATUSES
        for entry in session.ledger
    ):
        return False
    accepted = set(session.accepted_open_items)
    return not any(
        scope_of(node) == scope and node.status is NodeStatus.NEEDS_CLARIFICATION and node_key(node.id) not in accepted
        for node in session.graph.nodes
    )


def entering_focus(session: Session, domain: DomainKnowledge) -> str:
    """The focus a turn starts from, before any question is chosen.

    A scope the user asked for wins. Otherwise a subprocess that has been
    settled hands the conversation back to the main flow, without waiting for
    the navigator to think of it.
    """
    if valid_scope(domain, session.requested_focus):
        return str(session.requested_focus)
    if session.focus != MAIN_SCOPE and settled(session, session.focus):
        return MAIN_SCOPE
    return session.focus


def accept_focus(
    proposed: str | None,
    session: Session,
    domain: DomainKnowledge,
    candidates: Collection[Candidate],
    *,
    requested: str | None = None,
    scopes_raised_this_turn: Collection[str] = (),
) -> str:
    """Decide the focus for the next turn from what the navigator proposed.

    Args:
        proposed: The navigator's proposal. Anything that is not a scope of the
            process is ignored.
        session: The session, already on the focus this turn started from.
        domain: The knowledge base.
        candidates: This turn's ranked candidates.
        requested: A scope the user asked for this turn, which always wins.
        scopes_raised_this_turn: Scopes this turn's statements were about.

    Returns:
        The accepted focus: the request, the proposal if the rules allow it, or
        the current focus unchanged.
    """
    if valid_scope(domain, requested):
        return str(requested)
    current = session.focus
    if not valid_scope(domain, proposed) or proposed == current:
        return current
    assert proposed is not None  # narrowed by valid_scope

    if proposed == MAIN_SCOPE:
        # Leaving a subprocess unprompted is allowed only once it is settled.
        return MAIN_SCOPE if settled(session, current) else current

    if proposed in scopes_raised_this_turn:
        return proposed
    if not raised(session, domain, proposed) or settled(session, proposed):
        return current

    # The main flow has reached it. Move only if nothing more pressing is open where we are.
    here = min((c.rank for c in candidates if c.scope == current and not c.skip_offer), default=99)
    there = _best_rank_inside(session, proposed)
    return proposed if there < here else current


def _best_rank_inside(session: Session, scope: str) -> int:
    """The rank the subprocess's most pressing gap would have if it were the focus."""
    if any(scope_of(node) == scope and node.status is NodeStatus.NEEDS_CLARIFICATION for node in session.graph.nodes):
        return 1
    if any(
        entry.scope == scope and entry.priority is Priority.HIGH and entry.status in OPEN_STATUSES
        for entry in session.ledger
    ):
        return 4
    return 6
