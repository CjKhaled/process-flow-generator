"""The semantic document: structure, ordering, and determinism.

No diagram interchange is asserted here, because none is emitted -- geometry
belongs to the layouter, and the tests for it live in the integration suite,
against the file it produces. What matters at this level is that the document is
well formed BPMN in the order the layouter needs to read it.
"""

import xml.etree.ElementTree as ET

import pytest

from bpmn import document, semantics
from bpmn.document import BPMN_NS
from ir.models import EdgeType, NodeType, ProcessGraph
from tests.builders import branch, config, edge, graph, node, skeleton

ACTORS = ("HCP", "CM360", "PSM")
PHASES = skeleton("intake", "off_label", "duplicate", "onboarding")
NS = {"bpmn": BPMN_NS}


@pytest.fixture
def sample_graph() -> ProcessGraph:
    """A graph covering every element type the renderer knows."""
    return graph(
        nodes=(
            node("start", NodeType.START, actor="HCP", subprocess="intake"),
            node("transcribe", subprocess="intake", actor="CM360"),
            node("review", NodeType.SUBPROCESS, subprocess="off_label", actor="CM360"),
            node("gw", NodeType.GATEWAY, subprocess="duplicate", actor="CM360"),
            node("create", subprocess="duplicate", actor="PSM"),
            node("done", NodeType.TERMINAL, subprocess="onboarding", actor="PSM"),
            node("existing", NodeType.TERMINAL, subprocess="duplicate", actor="CM360"),
            node("note", NodeType.ANNOTATION, label="Status: PENDING", actor="PSM"),
        ),
        edges=(
            edge("start", "transcribe"),
            edge("transcribe", "review"),
            edge("review", "gw"),
            branch("gw", "create", "patient is new", order=0),
            branch("gw", "existing", "patient already exists", order=1),
            edge("create", "done"),
            edge("note", "create", EdgeType.ANNOTATES),
        ),
    )


def render(process: ProcessGraph) -> str:
    return document.render(semantics.translate(process, config(ACTORS), PHASES))


@pytest.fixture
def rendered(sample_graph: ProcessGraph) -> ET.Element:
    return ET.fromstring(render(sample_graph))


def test_the_document_parses(rendered: ET.Element) -> None:
    assert rendered.tag == f"{{{BPMN_NS}}}definitions"


def test_no_diagram_interchange_is_emitted(rendered: ET.Element) -> None:
    """The layouter discards existing DI, so emitting any would be work thrown away."""
    tags = {child.tag.split("}")[-1] for child in rendered.iter()}

    assert "BPMNDiagram" not in tags
    assert "BPMNPlane" not in tags
    assert "BPMNShape" not in tags


def test_there_is_one_pool_referencing_the_process(rendered: ET.Element) -> None:
    participants = rendered.findall("bpmn:collaboration/bpmn:participant", NS)
    process = rendered.find("bpmn:process", NS)

    assert len(participants) == 1
    assert process is not None
    assert participants[0].get("processRef") == process.get("id")


def test_the_pool_is_named_from_the_metadata(rendered: ET.Element) -> None:
    participant = rendered.find("bpmn:collaboration/bpmn:participant", NS)

    assert participant is not None
    assert participant.get("name") == "Intake & Enrollment"


def test_there_is_one_lane_per_actor_in_order(rendered: ET.Element) -> None:
    found = rendered.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)

    assert [lane.get("name") for lane in found] == list(ACTORS)


def test_every_flow_node_is_claimed_by_exactly_one_lane(rendered: ET.Element) -> None:
    """A node in no lane is drawn outside the pool; a node in two is a layout error."""
    refs = [str(item.text) for item in rendered.iter(f"{{{BPMN_NS}}}flowNodeRef")]
    process = rendered.find("bpmn:process", NS)
    assert process is not None
    flow_nodes = [
        str(child.get("id"))
        for child in process
        if child.tag.split("}")[-1] in {"startEvent", "endEvent", "task", "exclusiveGateway", "subProcess"}
    ]

    assert sorted(refs) == sorted(flow_nodes)
    assert len(refs) == len(set(refs))


def test_artifacts_are_emitted_after_every_flow_element(rendered: ET.Element) -> None:
    """tProcess is a sequence; an annotation among the tasks is out of order."""
    process = rendered.find("bpmn:process", NS)
    assert process is not None
    children = [child.tag.split("}")[-1] for child in process]
    artifacts = {"textAnnotation", "association"}
    first_artifact = next(index for index, tag in enumerate(children) if tag in artifacts)

    assert all(tag in artifacts for tag in children[first_artifact:])


def test_the_lane_set_comes_before_the_flow_elements(rendered: ET.Element) -> None:
    process = rendered.find("bpmn:process", NS)
    assert process is not None

    assert [child.tag.split("}")[-1] for child in process][0] == "laneSet"


def test_every_sequence_flow_resolves_to_declared_elements(rendered: ET.Element) -> None:
    """A dangling sourceRef makes the layouter reject the whole document."""
    process = rendered.find("bpmn:process", NS)
    assert process is not None
    declared = {child.get("id") for child in process}
    flows = process.findall("bpmn:sequenceFlow", NS)

    assert flows
    for flow in flows:
        assert flow.get("sourceRef") in declared
        assert flow.get("targetRef") in declared


def test_a_named_flow_carries_its_condition(rendered: ET.Element) -> None:
    named = {flow.get("name") for flow in rendered.findall("bpmn:process/bpmn:sequenceFlow", NS) if flow.get("name")}

    assert named == {"patient is new", "patient already exists"}


def test_the_annotation_text_survives(rendered: ET.Element) -> None:
    text = rendered.find("bpmn:process/bpmn:textAnnotation/bpmn:text", NS)

    assert text is not None
    assert text.text == "Status: PENDING"


def test_the_association_is_undirected(rendered: ET.Element) -> None:
    association = rendered.find("bpmn:process/bpmn:association", NS)

    assert association is not None
    assert association.get("associationDirection") == "None"


def test_identical_input_yields_identical_output(sample_graph: ProcessGraph) -> None:
    """The stage's headline guarantee; a diff here means something leaked in."""
    assert render(sample_graph) == render(sample_graph)


def test_the_output_carries_no_timestamp_or_generated_id(sample_graph: ProcessGraph) -> None:
    """The usual causes of a file that differs from itself."""
    rendered_text = render(sample_graph)

    assert "20" + "26-" not in rendered_text  # a date, split so this file is not the match
    assert not any(len(token) == 36 and token.count("-") == 4 for token in rendered_text.split('"'))
