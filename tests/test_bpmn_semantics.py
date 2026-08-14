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
from ir.models import BranchAnswer, EdgeType, NodeStatus, NodeType, ProcessGraph
from ir.skeleton import Skeleton, SubprocessSpec
from tests.builders import branch, config, edge, graph, node, skeleton

SUBPROCESSES = ("intake", "off_label", "duplicate", "onboarding")


def translate(
    process: ProcessGraph,
    actors: tuple[str, ...] = ("CM360",),
    phases: Skeleton | None = None,
) -> semantics.Definitions:
    """Translate against a skeleton whose boxes are drawn in the first declared lane."""
    return semantics.translate(process, config(actors), phases or skeleton(*SUBPROCESSES, actor=actors[0]))


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
    assert association.target_id == semantics.annotation_element_id("a")


def test_an_annotation_gets_an_id_prefix_of_its_own() -> None:
    """The viewer restyles notes, and CSS can tell one shape from another only by id."""
    result = translate(graph((node("t"), node("a", NodeType.ANNOTATION)), (edge("a", "t", EdgeType.ANNOTATES),)))

    assert result.annotations[0].element_id == "Note_a"


def test_a_branchs_answer_becomes_the_flow_name() -> None:
    """A decision and two words, rather than a decision and two sentences."""
    result = translate(
        graph(
            (node("gw", NodeType.GATEWAY), node("y"), node("n")),
            (
                branch("gw", "y", "diagnosis code is off-label", order=0, answer=BranchAnswer.YES),
                branch("gw", "n", "diagnosis code is not off-label", order=1, answer=BranchAnswer.NO),
            ),
        )
    )

    assert [flow.name for flow in result.flows] == ["Yes", "No"]


def test_a_branch_with_no_answer_keeps_its_condition() -> None:
    """Not every decision is a yes/no question, and 'Yes' on a named outcome would be a lie."""
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


def test_flow_nodes_are_emitted_in_the_graphs_own_order() -> None:
    """The layouter has no partition option; declaration order is what it breaks ties on."""
    result = translate(graph((node("c"), node("a"), node("b")), ()))

    assert [item.node_id for item in result.flow_nodes] == ["c", "a", "b"]


def test_a_collapsed_box_stands_where_the_first_of_its_steps_stood() -> None:
    """The box takes the place of its steps, so it belongs where they were."""
    result = translate(
        graph(
            (
                node("before"),
                node("first_step", subprocess="off_label"),
                node("second_step", subprocess="off_label"),
                node("after"),
            ),
            (),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["before", "off_label", "after"]


# --- the collapse: a decision hands work off, and the diagram says so in one box ---


def test_the_steps_of_a_subprocess_are_not_drawn() -> None:
    """The whole point of the tag: eleven steps become one box."""
    result = translate(graph((node("a", subprocess="off_label"), node("b", subprocess="off_label")), ()))

    assert [item.node_id for item in result.flow_nodes] == ["off_label"]
    assert result.flow_nodes[0].kind is ElementKind.SUB_PROCESS
    assert result.flow_nodes[0].name == "Off Label"
    assert result.flow_nodes[0].element_id == "Node_sub_off_label"


def test_a_collapsed_box_is_drawn_in_the_lane_the_skeleton_declares() -> None:
    """It has no node to take a lane from, and the busiest lane is routinely the wrong answer."""
    phases = Skeleton(
        process_name="enrollment",
        subprocesses=(SubprocessSpec(name="off_label", label="Off-Label Review", actor="CM360", order_hint=1),),
    )
    result = translate(graph((node("a", subprocess="off_label", actor="PSM"),), ()), ("CM360", "PSM"), phases)

    assert result.flow_nodes[0].actor == "CM360"
    assert result.lanes[0].actor == "CM360"
    assert result.lanes[0].flow_node_ids == ("Node_sub_off_label",)


def test_a_lane_is_drawn_for_a_box_even_when_no_visible_node_uses_it() -> None:
    """Collapsing every node in a lane must not collapse the lane out from under the box."""
    phases = Skeleton(
        process_name="enrollment",
        subprocesses=(SubprocessSpec(name="off_label", label="Off-Label Review", actor="PSM", order_hint=1),),
    )
    result = translate(graph((node("a", subprocess="off_label", actor="CM360"),), ()), ("CM360", "PSM"), phases)

    assert [lane.actor for lane in result.lanes] == ["PSM"]


def test_a_terminal_inside_a_subprocess_folds_in_with_the_rest() -> None:
    """The box is itself the end of the path; an end event beside it would end the story twice."""
    result = translate(
        graph(
            (node("step", subprocess="duplicate"), node("ended", NodeType.TERMINAL, subprocess="duplicate")),
            (edge("step", "ended"),),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["duplicate"]
    assert result.flows == ()


def test_nothing_leaves_a_collapsed_box() -> None:
    """A decision hands work off, and at this level of the diagram that path is over."""
    result = translate(
        graph(
            (
                node("begin", NodeType.START),
                node("gw", NodeType.GATEWAY),
                node("step", subprocess="off_label"),
                node("carry_on"),
                node("ended", NodeType.TERMINAL),
            ),
            (
                edge("begin", "gw"),
                branch("gw", "step", "off-label", order=0),
                branch("gw", "carry_on", "on-label", order=1),
                edge("step", "carry_on"),
                edge("carry_on", "ended"),
            ),
        )
    )

    assert [(flow.source_id, flow.target_id) for flow in result.flows] == [
        (semantics.node_element_id("begin"), semantics.node_element_id("gw")),
        (semantics.node_element_id("gw"), "Node_sub_off_label"),
        (semantics.node_element_id("gw"), semantics.node_element_id("carry_on")),
        (semantics.node_element_id("carry_on"), semantics.node_element_id("ended")),
    ]


def test_one_box_may_hand_off_to_another() -> None:
    """The one thing that leaves a box, because the alternative is deleting a named section.

    A source that describes CM360's missing-info process and then the PSM's is
    still speaking at the level the boxes are drawn at. Pruning the second for
    sitting behind the first would lose a stretch of work the skeleton asked for
    by name.
    """
    result = translate(
        graph(
            (
                node("begin", NodeType.START),
                node("first", subprocess="off_label"),
                node("second", subprocess="duplicate"),
                node("inside", subprocess="duplicate"),
            ),
            (edge("begin", "first"), edge("first", "second"), edge("second", "inside")),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["begin", "off_label", "duplicate"]
    assert [(flow.source_id, flow.target_id) for flow in result.flows] == [
        (semantics.node_element_id("begin"), "Node_sub_off_label"),
        ("Node_sub_off_label", "Node_sub_duplicate"),
    ]


def test_what_a_handed_off_box_led_to_is_still_pruned() -> None:
    """The exception is one box reaching another, not a box reaching the main line again."""
    result = translate(
        graph(
            (
                node("begin", NodeType.START),
                node("first", subprocess="off_label"),
                node("second", subprocess="duplicate"),
                node("aftermath", NodeType.TERMINAL),
            ),
            (edge("begin", "first"), edge("first", "second"), edge("second", "aftermath")),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["begin", "off_label", "duplicate"]


def test_what_only_the_subprocess_led_to_is_pruned_away() -> None:
    """An end state a subprocess reached is part of the subprocess, not of this diagram."""
    result = translate(
        graph(
            (
                node("begin", NodeType.START),
                node("step", subprocess="off_label"),
                node("aftermath", NodeType.TERMINAL),
            ),
            (edge("begin", "step"), edge("step", "aftermath")),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["begin", "off_label"]


def test_what_the_main_line_also_reaches_survives_the_pruning() -> None:
    """A decision the subprocess happened to feed back into is still on the main line."""
    result = translate(
        graph(
            (
                node("begin", NodeType.START),
                node("gw", NodeType.GATEWAY),
                node("step", subprocess="off_label"),
                node("shared", NodeType.TERMINAL),
            ),
            (
                edge("begin", "gw"),
                branch("gw", "step", "off-label", order=0),
                branch("gw", "shared", "on-label", order=1),
                edge("step", "shared"),
            ),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["begin", "gw", "off_label", "shared"]


def test_a_start_inside_a_subprocess_is_hoisted_out() -> None:
    """A process without a visible entry point is not a process."""
    result = translate(
        graph(
            (node("begin", NodeType.START, subprocess="intake"), node("step", subprocess="intake")),
            (edge("begin", "step"),),
        )
    )

    assert [item.node_id for item in result.flow_nodes] == ["begin", "intake"]


def test_an_annotation_inside_a_subprocess_is_dropped_with_its_association() -> None:
    """A note about a step the diagram no longer shows has nothing to describe."""
    result = translate(
        graph(
            (node("step", subprocess="off_label"), node("note", NodeType.ANNOTATION, subprocess="off_label")),
            (edge("note", "step", EdgeType.ANNOTATES),),
        )
    )

    assert result.annotations == ()
    assert result.associations == ()


def test_an_annotation_outside_a_subprocess_re_points_at_the_box() -> None:
    """It still has something to describe: the box that swallowed the step."""
    result = translate(
        graph(
            (node("step", subprocess="off_label"), node("note", NodeType.ANNOTATION)),
            (edge("note", "step", EdgeType.ANNOTATES),),
        )
    )

    assert result.associations[0].source_id == "Node_sub_off_label"
    assert result.associations[0].target_id == semantics.annotation_element_id("note")


def test_an_edge_wholly_inside_a_subprocess_is_dropped() -> None:
    result = translate(graph((node("a", subprocess="off_label"), node("b", subprocess="off_label")), (edge("a", "b"),)))

    assert result.flows == ()


def test_branches_entering_the_same_box_merge_and_lose_their_labels() -> None:
    """Two reasons for reaching the same box; printing one of them would be a claim."""
    result = translate(
        graph(
            (
                node("gw", NodeType.GATEWAY),
                node("first", subprocess="off_label"),
                node("second", subprocess="off_label"),
            ),
            (
                branch("gw", "first", "no confirmed diagnosis", order=0),
                branch("gw", "second", "prescriber disagrees", order=1),
            ),
        )
    )

    assert len(result.flows) == 1
    assert result.flows[0].name is None


def test_merged_branches_that_agree_keep_their_label() -> None:
    """Nothing is lost by printing a condition both edges gave."""
    result = translate(
        graph(
            (
                node("gw", NodeType.GATEWAY),
                node("first", subprocess="off_label"),
                node("second", subprocess="off_label"),
            ),
            (
                branch("gw", "first", "off-label confirmed", order=0),
                branch("gw", "second", "off-label confirmed", order=1),
            ),
        )
    )

    assert [flow.name for flow in result.flows] == ["off-label confirmed"]


def test_merged_branches_giving_opposite_answers_lose_their_label() -> None:
    """One arrow cannot be both the Yes and the No, so it says neither."""
    result = translate(
        graph(
            (
                node("gw", NodeType.GATEWAY),
                node("first", subprocess="off_label"),
                node("second", subprocess="off_label"),
            ),
            (
                branch("gw", "first", "off-label", order=0, answer=BranchAnswer.YES),
                branch("gw", "second", "not off-label", order=1, answer=BranchAnswer.NO),
            ),
        )
    )

    assert [flow.name for flow in result.flows] == [None]


def test_two_untouched_edges_between_the_same_pair_are_both_kept() -> None:
    """Merging is the collapse cleaning up after itself, not a rule about the graph."""
    result = translate(
        graph(
            (node("gw", NodeType.GATEWAY), node("next")),
            (branch("gw", "next", "one way", order=0), branch("gw", "next", "the other", order=1)),
        )
    )

    assert [flow.name for flow in result.flows] == ["one way", "the other"]


def test_a_subprocess_the_skeleton_does_not_declare_stays_expanded() -> None:
    """The validator already reports the node; folding it away would hide that twice."""
    result = translate(graph((node("a", subprocess="invented"), node("b", subprocess="off_label")), ()))

    assert [item.node_id for item in result.flow_nodes] == ["a", "off_label"]


def test_a_subprocess_no_node_claims_gets_no_box() -> None:
    """A subprocess the source never described is an open question, not an empty box."""
    result = translate(graph((node("a"),), ()))

    assert [item.node_id for item in result.flow_nodes] == ["a"]


def test_element_ids_maps_a_hidden_node_to_its_box() -> None:
    """This is what keeps an open question raised inside a collapse clickable."""
    process = graph((node("hidden", subprocess="off_label"), node("shown")), ())

    assert semantics.element_ids(process, skeleton(*SUBPROCESSES)) == {
        "hidden": "Node_sub_off_label",
        "shown": semantics.node_element_id("shown"),
    }


def test_a_skeleton_naming_an_undeclared_lane_is_rejected() -> None:
    """A lane that does not exist is a config error, and stage 2 is where the two meet."""
    phases = Skeleton(
        process_name="enrollment",
        subprocesses=(SubprocessSpec(name="off_label", label="Off-Label", actor="Acme Corp", order_hint=1),),
    )

    with pytest.raises(ValueError, match="Acme Corp"):
        translate(graph((node("a"),), ()), ("CM360",), phases)


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
