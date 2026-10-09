"""Applying a patch to a graph.

Every operation, and every way one can fail to apply. A bad operation is skipped
and reported rather than raised, because the report is what the model is shown on
its repair turn.
"""

from ir.models import EdgeType, NodeOrigin, NodeStatus, NodeType, ProcessGraph
from session.patch import (
    AddEdge,
    AddNode,
    EdgeFields,
    GraphPatch,
    NodeFields,
    Operation,
    RemoveEdge,
    RemoveNode,
    UpdateEdge,
    UpdateNode,
    apply_patch,
    empty_graph,
)
from tests.builders import branch, edge, graph, node, ref
from validators.report import FindingCode


def patch(*operations: Operation) -> GraphPatch:
    return GraphPatch(operations=operations)


def base() -> ProcessGraph:
    return graph(
        nodes=(
            node("start", NodeType.START),
            node("gw", NodeType.GATEWAY),
            node("end_yes", NodeType.TERMINAL),
            node("end_no", NodeType.TERMINAL),
        ),
        edges=(edge("start", "gw"), branch("gw", "end_yes", "yes", 0), branch("gw", "end_no", "no", 1)),
    )


def test_the_first_turn_is_a_patch_against_an_empty_graph() -> None:
    result, findings = apply_patch(
        empty_graph("enrollment"),
        patch(
            AddNode(op="add_node", node=node("start", NodeType.START)),
            AddNode(op="add_node", node=node("end", NodeType.TERMINAL)),
            AddEdge(op="add_edge", edge=edge("start", "end")),
        ),
    )

    assert findings == ()
    assert [item.id for item in result.nodes] == ["start", "end"]
    assert len(result.edges) == 1


def test_an_empty_patch_changes_nothing() -> None:
    result, findings = apply_patch(base(), patch())

    assert result == base() and findings == ()


def test_the_graph_given_is_never_modified() -> None:
    original = base()

    apply_patch(original, patch(RemoveNode(op="remove_node", id="end_no", reason_statement_ids=("s_0001",))))

    assert original == base()


def test_update_node_changes_only_the_named_fields() -> None:
    result, _ = apply_patch(
        base(), patch(UpdateNode(op="update_node", id="gw", fields=NodeFields(label="Is it complete?")))
    )
    changed = next(item for item in result.nodes if item.id == "gw")

    assert changed.label == "Is it complete?"
    assert changed.actor == "CM360" and changed.type is NodeType.GATEWAY


def test_a_null_field_means_unchanged_and_clear_is_how_one_is_emptied() -> None:
    """A model writes explicit nulls for fields it has no view on, so null cannot mean 'empty it'."""
    tagged = graph(nodes=(node("a", subprocess="off_label_review", detail="some detail"),), edges=())

    kept, _ = apply_patch(tagged, patch(UpdateNode(op="update_node", id="a", fields=NodeFields(subprocess=None))))
    cleared, _ = apply_patch(
        tagged, patch(UpdateNode(op="update_node", id="a", fields=NodeFields(clear=("subprocess", "detail"))))
    )

    assert kept.nodes[0].subprocess == "off_label_review"
    assert cleared.nodes[0].subprocess is None and cleared.nodes[0].detail is None


def test_a_rule_terminal_is_promoted_when_an_answer_states_its_outcome() -> None:
    open_end = graph(
        nodes=(
            node(
                "end_open",
                NodeType.TERMINAL,
                status=NodeStatus.NEEDS_CLARIFICATION,
                detail="not stated",
                origin=NodeOrigin.RULE,
            ),
        ),
        edges=(),
    )
    fields = NodeFields(
        status=NodeStatus.STATED,
        origin=NodeOrigin.SOURCE,
        label="Enrollment cancelled",
        evidence=(ref("s_0009", "it is cancelled"),),
        clear=("detail",),
    )

    result, findings = apply_patch(open_end, patch(UpdateNode(op="update_node", id="end_open", fields=fields)))

    assert findings == ()
    assert result.nodes[0].origin is NodeOrigin.SOURCE
    assert result.nodes[0].status is NodeStatus.STATED
    assert result.nodes[0].evidence[0].statement_id == "s_0009"


def test_removing_a_node_removes_its_edges() -> None:
    result, findings = apply_patch(
        base(), patch(RemoveNode(op="remove_node", id="end_no", reason_statement_ids=("s_0004",)))
    )

    assert findings == ()
    assert "end_no" not in {item.id for item in result.nodes}
    assert all("end_no" not in (item.from_id, item.to_id) for item in result.edges)
    assert len(result.edges) == 2


def test_update_edge_can_repoint_a_branch() -> None:
    result, findings = apply_patch(
        base(),
        patch(
            AddNode(op="add_node", node=node("notify")),
            UpdateEdge(op="update_edge", from_id="gw", to_id="end_no", order=1, fields=EdgeFields(to_id="notify")),
            AddEdge(op="add_edge", edge=edge("notify", "end_no")),
        ),
    )

    assert findings == ()
    assert ("gw", "notify", EdgeType.BRANCH) in {(item.from_id, item.to_id, item.type) for item in result.edges}


def test_an_edge_is_found_by_its_ends_when_the_order_given_is_wrong() -> None:
    """Edges have no id, and the order is the part a model misremembers."""
    result, findings = apply_patch(
        base(),
        patch(
            UpdateEdge(op="update_edge", from_id="gw", to_id="end_no", order=7, fields=EdgeFields(condition="never"))
        ),
    )

    assert findings == ()
    assert next(item for item in result.edges if item.to_id == "end_no").condition == "never"


def test_remove_edge_leaves_both_nodes() -> None:
    result, findings = apply_patch(
        base(),
        patch(RemoveEdge(op="remove_edge", from_id="gw", to_id="end_no", order=1, reason_statement_ids=("s_0002",))),
    )

    assert findings == ()
    assert len(result.nodes) == 4 and len(result.edges) == 2


def test_adding_a_node_whose_id_is_taken_is_reported_and_skipped() -> None:
    result, findings = apply_patch(base(), patch(AddNode(op="add_node", node=node("gw", label="Another"))))

    assert [finding.code for finding in findings] == [FindingCode.PATCH_DUPLICATE_NODE]
    assert findings[0].node_ids == ("gw",)
    assert result == base()


def test_updating_or_removing_a_node_that_is_not_there_is_reported() -> None:
    _, findings = apply_patch(
        base(),
        patch(
            UpdateNode(op="update_node", id="ghost", fields=NodeFields(label="x")),
            RemoveNode(op="remove_node", id="phantom", reason_statement_ids=("s_0001",)),
        ),
    )

    assert [finding.code for finding in findings] == [FindingCode.PATCH_UNKNOWN_NODE] * 2
    assert "ghost" in findings[0].message and "phantom" in findings[1].message


def test_updating_or_removing_an_edge_that_is_not_there_is_reported() -> None:
    _, findings = apply_patch(
        base(),
        patch(
            UpdateEdge(op="update_edge", from_id="start", to_id="end_no", order=0, fields=EdgeFields(order=2)),
            RemoveEdge(op="remove_edge", from_id="end_yes", to_id="gw", order=0, reason_statement_ids=("s_0001",)),
        ),
    )

    assert [finding.code for finding in findings] == [FindingCode.PATCH_UNKNOWN_EDGE] * 2


def test_a_bad_operation_does_not_stop_the_rest_of_the_patch() -> None:
    """The findings should describe everything wrong with a patch at once, not the first thing."""
    result, findings = apply_patch(
        base(),
        patch(
            UpdateNode(op="update_node", id="ghost", fields=NodeFields(label="x")),
            UpdateNode(op="update_node", id="gw", fields=NodeFields(label="Still applied")),
        ),
    )

    assert len(findings) == 1
    assert next(item for item in result.nodes if item.id == "gw").label == "Still applied"


def test_patch_findings_are_structural_so_they_earn_a_repair_turn() -> None:
    _, findings = apply_patch(base(), patch(AddNode(op="add_node", node=node("gw"))))

    assert findings[0].severity == "structural"


def test_a_step_learned_later_is_placed_after_the_step_that_leads_to_it() -> None:
    """Node order is the narrative order stage 2 lays out by; a patch can only append."""
    result, _ = apply_patch(
        base(),
        patch(
            AddNode(op="add_node", node=node("check")),
            AddNode(op="add_node", node=node("log")),
            RemoveEdge(op="remove_edge", from_id="start", to_id="gw", order=0, reason_statement_ids=("s_0002",)),
            AddEdge(op="add_edge", edge=edge("start", "check")),
            AddEdge(op="add_edge", edge=edge("check", "log")),
            AddEdge(op="add_edge", edge=edge("log", "gw")),
        ),
    )

    assert [item.id for item in result.nodes] == ["start", "check", "log", "gw", "end_yes", "end_no"]


def test_an_annotation_added_later_follows_the_step_it_describes() -> None:
    result, _ = apply_patch(
        base(),
        patch(
            AddNode(op="add_node", node=node("note", NodeType.ANNOTATION)),
            AddEdge(op="add_edge", edge=edge("note", "gw", EdgeType.ANNOTATES)),
        ),
    )

    assert [item.id for item in result.nodes] == ["start", "gw", "note", "end_yes", "end_no"]


def test_existing_nodes_never_move() -> None:
    result, _ = apply_patch(
        base(), patch(AddNode(op="add_node", node=node("extra")), AddEdge(op="add_edge", edge=edge("gw", "extra")))
    )

    assert [item.id for item in result.nodes if item.id != "extra"] == [item.id for item in base().nodes]


def test_a_patch_round_trips_through_json_with_its_operation_types_intact() -> None:
    """The session file stores each turn's patch, so the discriminator has to survive it."""
    original = patch(
        AddNode(op="add_node", node=node("a")),
        RemoveNode(op="remove_node", id="b", reason_statement_ids=("s_0001",)),
    )

    restored = GraphPatch.model_validate_json(original.model_dump_json())

    assert restored == original
    assert isinstance(restored.operations[1], RemoveNode)
