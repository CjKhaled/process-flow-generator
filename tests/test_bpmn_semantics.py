"""The graph-to-BPMN mapping, which needs no coordinates to check.

Two things are being tested here, and the second is easy to overlook. The first
is the mapping itself -- which node becomes which element, which way an
association points. The second is **emission order**, which is this stage's only
influence over the drawing: the layouter computes all geometry and breaks its
ties on BPMN declaration order, so the sequence produced here is the difference
between a readable diagram and a scrambled one.
"""

import pytest

from bpmn import semantics
from bpmn.semantics import ElementKind
from ir.models import EdgeType, NodeStatus, NodeType, ProcessGraph
from ir.skeleton import Skeleton
from tests.builders import branch, config, edge, graph, node, skeleton

PHASES = skeleton("intake", "off_label", "duplicate", "onboarding")


def translate(
    process: ProcessGraph,
    actors: tuple[str, ...] = ("CM360",),
    phases: Skeleton = PHASES,
) -> semantics.Definitions:
    return semantics.translate(process, config(actors), phases)


@pytest.mark.parametrize(
    ("node_type", "expected"),
    [
        (NodeType.START, ElementKind.START_EVENT),
        (NodeType.TERMINAL, ElementKind.END_EVENT),
        (NodeType.TASK, ElementKind.TASK),
        (NodeType.GATEWAY, ElementKind.EXCLUSIVE_GATEWAY),
        (NodeType.SUBPROCESS, ElementKind.SUB_PROCESS),
    ],
)
def test_every_node_type_maps_to_its_bpmn_element(node_type: NodeType, expected: ElementKind) -> None:
    result = translate(graph((node("n", node_type),), ()))

    assert result.flow_nodes[0].kind is expected


def test_a_needs_clarification_terminal_is_an_ordinary_end_event() -> None:
    """Marking it up is stage 3's job; a special notation here would overclaim."""
    result = translate(
        graph((node("t", NodeType.TERMINAL, status=NodeStatus.NEEDS_CLARIFICATION, detail="unstated"),), ())
    )

    assert result.flow_nodes[0].kind is ElementKind.END_EVENT


def test_the_label_becomes_the_element_name() -> None:
    result = translate(graph((node("t", label="Transcribe PEF into CRM"),), ()))

    assert result.flow_nodes[0].name == "Transcribe PEF into CRM"


def test_an_annotation_is_an_artifact_not_a_flow_node() -> None:
    """A textAnnotation among the flow nodes is a file that opens blank."""
    result = translate(
        graph(
            (node("t"), node("a", NodeType.ANNOTATION, label="Status: PENDING")), (edge("a", "t", EdgeType.ANNOTATES),)
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["t"]
    assert [item.text for item in result.annotations] == ["Status: PENDING"]


def test_an_annotation_is_never_listed_in_a_lane() -> None:
    """flowNodeRef takes flow nodes only, whatever band the note is drawn in."""
    result = translate(graph((node("t"), node("a", NodeType.ANNOTATION)), (edge("a", "t", EdgeType.ANNOTATES),)))

    assert result.lanes[0].flow_node_ids == (semantics.node_element_id("t"),)


def test_an_association_points_from_the_annotated_element_to_the_note() -> None:
    """The IR runs this edge the other way; the flip happens exactly once, here."""
    result = translate(graph((node("t"), node("a", NodeType.ANNOTATION)), (edge("a", "t", EdgeType.ANNOTATES),)))

    association = result.associations[0]
    assert association.source_id == semantics.node_element_id("t")
    assert association.target_id == semantics.node_element_id("a")


def test_a_branch_condition_becomes_the_flow_name() -> None:
    """It is the label on the arrow, not an executable predicate."""
    result = translate(
        graph(
            (node("gw", NodeType.GATEWAY), node("y"), node("n")),
            (branch("gw", "y", "Patient is 18 or older", order=0), branch("gw", "n", "Otherwise", order=1)),
        )
    )

    assert [flow.name for flow in result.flows] == ["Patient is 18 or older", "Otherwise"]


def test_a_plain_sequence_flow_is_unnamed() -> None:
    result = translate(graph((node("a"), node("b")), (edge("a", "b"),)))

    assert result.flows[0].name is None


# --- emission order: the only lever this stage has over the layout ---


def test_branches_are_emitted_in_edge_order() -> None:
    """Edge.order decides which way a gateway's branches are drawn."""
    result = translate(
        graph(
            (node("gw", NodeType.GATEWAY), node("second"), node("first")),
            (branch("gw", "second", "otherwise", order=1), branch("gw", "first", "patient is new", order=0)),
        )
    )

    assert [flow.target_id for flow in result.flows] == [
        semantics.node_element_id("first"),
        semantics.node_element_id("second"),
    ]


def test_flow_nodes_are_emitted_in_skeleton_order() -> None:
    """The layouter has no partition option; declaration order is what orders the phases."""
    result = translate(
        graph(
            (
                node("late", subprocess="onboarding"),
                node("early", subprocess="intake"),
                node("middle", subprocess="duplicate"),
            ),
            (),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["early", "middle", "late"]


def test_a_node_outside_every_subprocess_is_emitted_last() -> None:
    """The skeleton is the expected spine, so anything outside it is an addendum."""
    result = translate(graph((node("loose"), node("placed", subprocess="intake")), ()))

    assert [item.node_id for item in result.flow_nodes] == ["placed", "loose"]


def test_emission_order_is_stable_for_nodes_in_the_same_subprocess() -> None:
    """Ties keep the graph's own order, so a stable input gives a stable document."""
    result = translate(
        graph((node("c", subprocess="intake"), node("a", subprocess="intake"), node("b", subprocess="intake")), ())
    )

    assert [item.node_id for item in result.flow_nodes] == ["c", "a", "b"]


# --- lanes ---


def test_lane_order_follows_the_declaration_not_the_graph() -> None:
    """metadata.yaml decides which lane is on top, not whichever node came first."""
    nodes = (node("a", actor="JCRM"), node("b", actor="HCP"), node("c", actor="CM360"))

    assert semantics.lane_order(nodes, ("HCP", "CM360", "JCRM")) == ("HCP", "CM360", "JCRM")


def test_lane_order_omits_actors_no_node_uses() -> None:
    """A declared-but-unused actor would cost an empty band the reader scrolls past."""
    nodes = (node("a", actor="HCP"), node("b", actor="PSM"))

    assert semantics.lane_order(nodes, ("HCP", "Patient", "PSM", "JCRM")) == ("HCP", "PSM")


def test_lane_order_rejects_an_undeclared_actor() -> None:
    """Stage 1 cannot check this -- the validator never sees metadata.yaml -- so stage 2 must."""
    nodes = (node("a", actor="HCP"), node("b", actor="Acme Corp"))

    with pytest.raises(ValueError, match="Acme Corp"):
        semantics.lane_order(nodes, ("HCP", "PSM"))


def test_each_lane_owns_only_its_own_nodes() -> None:
    process = graph((node("a", actor="HCP"), node("b", actor="PSM"), node("c", actor="HCP")), ())
    result = translate(process, ("HCP", "PSM"))

    assert result.lanes[0].flow_node_ids == (semantics.node_element_id("a"), semantics.node_element_id("c"))
    assert result.lanes[1].flow_node_ids == (semantics.node_element_id("b"),)


def test_every_flow_node_belongs_to_exactly_one_lane() -> None:
    process = graph((node("a", actor="HCP"), node("b", actor="PSM"), node("c", actor="HCP")), ())
    result = translate(process, ("HCP", "PSM"))

    owned = [item for lane in result.lanes for item in lane.flow_node_ids]
    assert sorted(owned) == sorted(item.element_id for item in result.flow_nodes)


# --- ids ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SP Biologics", "SP_Biologics"),
        ("CM360", "CM360"),
        ("360Hub", "_360Hub"),
        ("a-b.c", "a_b_c"),
    ],
)
def test_names_are_slugged_into_valid_xml_ids(raw: str, expected: str) -> None:
    """BPMN ids are NCNames: no spaces, no punctuation, never a leading digit."""
    assert semantics.ncname(raw) == expected


def test_ids_come_from_the_metadata_not_the_graphs_own_label() -> None:
    """A model may name the graph anything; stage 1 warns rather than failing."""
    result = translate(graph((node("a"),), (), name="Some Label The Model Chose"))

    assert result.process_id == "Process_enrollment"


def test_ids_are_derived_from_the_graph_not_generated() -> None:
    """Two translations of the same graph must agree, or the output is not reproducible."""
    process = graph((node("a"), node("b")), (edge("a", "b"),))

    first, second = translate(process), translate(process)
    assert [item.element_id for item in first.flow_nodes] == [item.element_id for item in second.flow_nodes]
    assert [item.element_id for item in first.flows] == [item.element_id for item in second.flows]


def test_a_flow_keeps_the_edge_index_it_came_from() -> None:
    """Sorting for emission must not lose which IR edge a flow is; the index is its identity."""
    process = graph((node("a"), node("b"), node("c")), (edge("b", "c"), edge("a", "b")))

    by_id = {flow.element_id: flow.edge_index for flow in translate(process).flows}
    assert by_id == {"Flow_0": 0, "Flow_1": 1}
