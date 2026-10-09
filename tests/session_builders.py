"""Sessions, patches and agent answers for the conversation's tests.

Kept beside :mod:`tests.builders`, which builds graphs: these build the things a
session is made of, so a test can say what is true of the conversation in a line
or two and spend the rest on the behaviour it is about.
"""

from ir.models import Edge, Node, NodeOrigin, NodeStatus, NodeType
from knowledge.loader import DomainKnowledge
from session.models import LaneStatus, Session, SessionLane, Statement, StatementOrigin
from session.orchestrator import new_session, resolve_default_lane
from session.patch import AddEdge, AddNode, GraphPatch, Operation
from tests.builders import branch, edge, node, ref

DESCRIPTION = (
    "The HCP faxes the enrollment form to the vendor.\n"
    "The vendor keys the form into the CRM.\n"
    "If the form is complete, the patient is enrolled."
)
"""Three statements: a start, a task, and a decision with only its happy path."""


def patch(*operations: Operation) -> GraphPatch:
    return GraphPatch(operations=operations)


def add(item: Node | Edge) -> Operation:
    """Wrap a node or an edge in the operation that adds it."""
    if isinstance(item, Node):
        return AddNode(op="add_node", node=item)
    return AddEdge(op="add_edge", edge=item)


def session_with(
    domain: DomainKnowledge,
    *texts: str,
    lanes: tuple[tuple[str, str | None], ...] = (("HCP", "hcp_office"), ("Vendor", "external_vendor")),
    default: str | None = "CRM",
) -> Session:
    """A session that has heard some statements and learned some lanes.

    Args:
        domain: The knowledge base.
        texts: Statements, numbered ``s_0001`` onwards, as from a first description.
        lanes: ``(name, persona)`` for each lane to add.
        default: A lane to make the default in the placeholder's place, or None
            to leave the placeholder as it starts.
    """
    session = new_session("test", domain)
    session.turn = 1
    for index, text in enumerate(texts or DESCRIPTION.splitlines(), start=1):
        session.corpus.append(
            Statement(id=f"s_{index:04d}", origin=StatementOrigin.INITIAL_DESCRIPTION, turn=1, raw_text=text)
        )
    for name, persona in lanes:
        session.lanes.append(SessionLane(name=name, persona=persona))
    if default is not None:
        session.lanes.append(
            SessionLane(name=default, persona=domain.process.default_persona, status=LaneStatus.CONFIRMED)
        )
        resolve_default_lane(session, default)
    return session


def first_patch() -> GraphPatch:
    """The graph :data:`DESCRIPTION` supports: valid, fully cited, one outcome left open."""
    return patch(
        add(node("start", NodeType.START, actor="HCP", evidence=(ref("s_0001", "The HCP faxes the enrollment form"),))),
        add(node("key_form", actor="Vendor", evidence=(ref("s_0002", "The vendor keys the form"),))),
        add(
            node("gw_complete", NodeType.GATEWAY, actor="Vendor", evidence=(ref("s_0003", "If the form is complete"),))
        ),
        add(node("end_enrolled", NodeType.TERMINAL, actor="CRM", evidence=(ref("s_0003", "the patient is enrolled"),))),
        add(
            node(
                "end_incomplete",
                NodeType.TERMINAL,
                actor="Vendor",
                status=NodeStatus.NEEDS_CLARIFICATION,
                detail="What happens when the form is not complete is not stated.",
                origin=NodeOrigin.RULE,
            )
        ),
        add(edge("start", "key_form")),
        add(edge("key_form", "gw_complete")),
        add(
            branch(
                "gw_complete",
                "end_enrolled",
                "the form is complete",
                0,
                evidence=(ref("s_0003", "If the form is complete"),),
            )
        ),
        add(branch("gw_complete", "end_incomplete", "the form is not complete", 1)),
    )
