"""A master graph that touches all four subprocesses.

The shape a real session's graph has once a conversation has got somewhere: a
main line whose decisions hand work off, and tagged steps for each hand-off that
rejoin the main line, end the process, or do both. Shared by the slicing, view
and close-out tests so they all cut the same graph.
"""

from ir.models import Edge, EdgeType, Node, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from knowledge.loader import DomainKnowledge
from session.models import Session, SessionLane, Statement, StatementOrigin
from session.orchestrator import new_session, resolve_default_lane
from tests.builders import branch, edge, graph, node, ref

TEXT = "The whole process, as one statement that every step in this fixture cites."

LANES = (
    ("HCP", "hcp_office"),
    ("Vendor", "external_vendor"),
    ("PSM", "hub_case_owner"),
    ("Manager", "manager"),
    ("CRM", "crm_automation"),
)


def cited(
    node_id: str,
    node_type: NodeType = NodeType.TASK,
    *,
    actor: str,
    subprocess: str | None = None,
    label: str | None = None,
) -> Node:
    """A stated node resting on the fixture's one statement."""
    return node(
        node_id,
        node_type,
        actor=actor,
        subprocess=subprocess,
        label=label,
        evidence=(ref("s_0001", "The whole process"),),
    )


def when(from_id: str, to_id: str, condition: str, order: int) -> Edge:
    """A cited branch."""
    return branch(from_id, to_id, condition, order, evidence=(ref("s_0001", "as one statement"),))


def master_graph() -> ProcessGraph:
    """Main line: start -> key -> duplicate? -> eligible? -> missing? -> enrolled."""
    nodes = (
        cited("start", NodeType.START, actor="HCP"),
        cited("key_form", actor="Vendor"),
        cited("gw_duplicate", NodeType.GATEWAY, actor="Vendor"),
        # duplicate_handling: rejoins the main line, or ends the process.
        cited("dup_compare", actor="Vendor", subprocess="duplicate_handling"),
        cited("gw_same", NodeType.GATEWAY, actor="Vendor", subprocess="duplicate_handling"),
        cited("dup_attach", actor="Vendor", subprocess="duplicate_handling"),
        cited("gw_eligible", NodeType.GATEWAY, actor="Vendor"),
        # off_label_review: two ways out, one to a boundary and one unstated.
        cited("ol_call", actor="PSM", subprocess="off_label_review"),
        cited("gw_confirms", NodeType.GATEWAY, actor="PSM", subprocess="off_label_review"),
        node(
            "ol_open",
            NodeType.TERMINAL,
            actor="PSM",
            subprocess="off_label_review",
            status=NodeStatus.NEEDS_CLARIFICATION,
            detail="What happens when the prescriber does not confirm is not stated.",
            origin=NodeOrigin.RULE,
        ),
        cited("ol_note", NodeType.ANNOTATION, actor="PSM", subprocess="off_label_review", label="Status = REVIEW"),
        cited("gw_missing", NodeType.GATEWAY, actor="CRM"),
        # missing_info_hcp: a loop inside, then back to the main line or out.
        cited("mi_fax", actor="Vendor", subprocess="missing_info_hcp"),
        cited("gw_received", NodeType.GATEWAY, actor="Vendor", subprocess="missing_info_hcp"),
        cited("mi_escalate", actor="PSM", subprocess="missing_info_hcp"),
        cited("gw_consent", NodeType.GATEWAY, actor="CRM"),
        # missing_info_patient: entered from the main line at two points.
        cited("pt_call", actor="PSM", subprocess="missing_info_patient"),
        cited("pt_letter", actor="PSM", subprocess="missing_info_patient"),
        cited("gw_approves", NodeType.GATEWAY, actor="Manager", subprocess="missing_info_patient"),
        cited("enroll", actor="CRM"),
        cited("end_enrolled", NodeType.TERMINAL, actor="CRM", label="Handed off to benefits investigation"),
        cited("end_closed", NodeType.TERMINAL, actor="PSM", label="Closed, not enrolled"),
    )
    edges = (
        edge("start", "key_form"),
        edge("key_form", "gw_duplicate"),
        when("gw_duplicate", "dup_compare", "a possible match is found", 0),
        when("gw_duplicate", "gw_eligible", "no match", 1),
        edge("dup_compare", "gw_same"),
        when("gw_same", "dup_attach", "it is the same patient", 0),
        when("gw_same", "gw_eligible", "it is a different patient", 1),
        edge("dup_attach", "end_closed"),
        when("gw_eligible", "gw_missing", "the diagnosis is on-label", 0),
        when("gw_eligible", "ol_call", "the diagnosis is not clearly on-label", 1),
        edge("ol_call", "gw_confirms"),
        when("gw_confirms", "gw_missing", "the prescriber confirms", 0),
        branch("gw_confirms", "ol_open", "the prescriber does not confirm", 1),
        edge("ol_note", "ol_call", EdgeType.ANNOTATES),
        when("gw_missing", "mi_fax", "HCP items are missing", 0),
        when("gw_missing", "gw_consent", "nothing is missing from the HCP", 1),
        edge("mi_fax", "gw_received"),
        when("gw_received", "gw_consent", "the information arrives", 0),
        when("gw_received", "mi_escalate", "the office does not respond", 1),
        edge("mi_escalate", "mi_fax"),
        when("gw_consent", "enroll", "consent is on file", 0),
        when("gw_consent", "pt_call", "consent is missing", 1),
        when("gw_received", "pt_letter", "the office says to ask the patient", 2),
        edge("pt_call", "gw_approves"),
        edge("pt_letter", "gw_approves"),
        when("gw_approves", "enroll", "the patient responds", 0),
        when("gw_approves", "end_closed", "the manager approves cancellation", 1),
        edge("enroll", "end_enrolled"),
    )
    return graph(nodes, edges, name="enrollment_and_intake")


def master_session(domain: DomainKnowledge) -> Session:
    """A session holding :func:`master_graph`, with the lanes it uses and the statement it cites."""
    session = new_session("master", domain)
    session.turn = 1
    session.corpus.append(Statement(id="s_0001", origin=StatementOrigin.INITIAL_DESCRIPTION, turn=1, raw_text=TEXT))
    for name, persona in LANES:
        session.lanes.append(SessionLane(name=name, persona=persona))
    resolve_default_lane(session, "CRM")
    session.graph = master_graph()
    return session
