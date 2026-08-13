"""Schema round-trip tests for the IR."""

import pytest
from pydantic import ValidationError

from ir.models import Edge, EdgeType, Node, NodeStatus, NodeType, ProcessGraph
from ir.process_config import load_process_config
from ir.skeleton import load_skeleton
from tests.conftest import ENROLLMENT_DIR


def test_process_graph_round_trips_through_json(valid_graph: ProcessGraph) -> None:
    """A graph serialised to JSON and back is equal to the original."""
    restored = ProcessGraph.model_validate_json(valid_graph.model_dump_json())

    assert restored == valid_graph


def test_round_trip_preserves_enum_values(valid_graph: ProcessGraph) -> None:
    """Enums survive the round trip as enums, not bare strings."""
    restored = ProcessGraph.model_validate_json(valid_graph.model_dump_json())
    start = next(n for n in restored.nodes if n.id == "start_intake")
    annotates = next(e for e in restored.edges if e.type is EdgeType.ANNOTATES)

    assert start.type is NodeType.START
    assert start.status is NodeStatus.STATED
    assert annotates.to_id == "create_patient_record"


def test_enum_values_serialise_as_lowercase_strings(valid_graph: ProcessGraph) -> None:
    """The JSON on disk uses the wire vocabulary, not Python enum names."""
    dumped = valid_graph.model_dump(mode="json")

    assert dumped["nodes"][0]["type"] == "start"
    assert dumped["nodes"][0]["status"] == "stated"


def test_optional_fields_default_to_empty() -> None:
    """A minimal node carries no actor, subprocess, detail, or alternatives."""
    minimal = Node(id="n", type=NodeType.TASK, label="N", status=NodeStatus.STATED)

    assert minimal.actor is None
    assert minimal.subprocess is None
    assert minimal.detail is None
    assert minimal.alternatives == ()


def test_graph_is_immutable(valid_graph: ProcessGraph) -> None:
    """The graph is the in-memory source of truth and cannot be mutated in place."""
    with pytest.raises(ValidationError):
        valid_graph.nodes[0].label = "changed"

    assert isinstance(valid_graph.nodes, tuple)
    assert isinstance(valid_graph.edges, tuple)


def test_unknown_fields_are_rejected() -> None:
    """extra='forbid' keeps the structured-output schema closed."""
    with pytest.raises(ValidationError):
        Node.model_validate(
            {"id": "n", "type": "task", "label": "N", "status": "stated", "swimlane": "left"},
        )


def test_there_is_no_middle_status() -> None:
    """'inferred' was removed deliberately; the schema must not quietly accept it again."""
    assert [status.value for status in NodeStatus] == ["stated", "needs_clarification"]
    with pytest.raises(ValidationError):
        Node.model_validate({"id": "n", "type": "task", "label": "N", "status": "inferred"})


def test_empty_identifiers_are_rejected() -> None:
    """Empty ids and labels are shape defects, so Pydantic catches them for a mechanical retry."""
    with pytest.raises(ValidationError):
        Node.model_validate({"id": "", "type": "task", "label": "N", "status": "stated"})
    with pytest.raises(ValidationError):
        Edge.model_validate({"from_id": "a", "to_id": "b", "type": "precedes", "order": -1})


def test_pydantic_does_not_enforce_graph_semantics() -> None:
    """Broken graphs must be constructible, or the validator's fixtures could not exist."""
    broken = ProcessGraph(
        process_name="p",
        nodes=(
            Node(id="dup", type=NodeType.START, label="A", status=NodeStatus.STATED),
            Node(id="dup", type=NodeType.TASK, label="B", status=NodeStatus.STATED),
        ),
        edges=(Edge(from_id="dup", to_id="nowhere", type=EdgeType.PRECEDES, order=0),),
    )

    assert len(broken.nodes) == 2
    assert broken.edges[0].to_id == "nowhere"


def test_enrollment_skeleton_lists_the_five_required_subprocesses() -> None:
    """The skeleton on disk matches the documented enrollment subprocesses."""
    skeleton = load_skeleton(ENROLLMENT_DIR / "skeleton.json")

    assert skeleton.required_names == {"intake", "off_label", "duplicate", "missing_info", "onboarding"}
    assert [spec.name for spec in skeleton.in_hint_order()][:3] == ["intake", "off_label", "duplicate"]


def test_enrollment_metadata_loads() -> None:
    """The process config on disk parses and carries the actor vocabulary."""
    config = load_process_config(ENROLLMENT_DIR)

    assert config.process_name == "enrollment"
    assert "CM360" in config.actors
    assert config.glossary["PEF"] == "Patient Enrollment Form"
    assert config.model_id is None
