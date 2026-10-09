"""Colour written into the diagram file rather than into a stylesheet.

The point of doing it here is that the colour travels: a colleague opening
``diagram.bpmn`` in Camunda sees what the page sees. So these assert on the
attributes bpmn-js actually reads, which is the only thing that makes that true.
"""

import xml.etree.ElementTree as ET

import pytest

from bpmn.colors import COLOR_NS, EVENT, SUBPROCESS, apply

LAID_OUT = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" id="Definitions_stub">
  <bpmn:process id="Process_stub">
    <bpmn:startEvent id="Node_start" name="HCP faxes the PEF" />
    <bpmn:task id="Node_task" name="Transcribe the PEF" />
    <bpmn:exclusiveGateway id="Node_gw" name="Is it off-label?" />
    <bpmn:subProcess id="Node_sub_off_label" name="Off-Label Review" />
    <bpmn:endEvent id="Node_end" name="Enrolled" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_stub">
    <bpmndi:BPMNPlane id="BPMNPlane_stub" bpmnElement="Process_stub">
      <bpmndi:BPMNShape id="Shape_start" bpmnElement="Node_start">
        <dc:Bounds x="10" y="10" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_task" bpmnElement="Node_task">
        <dc:Bounds x="100" y="10" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_gw" bpmnElement="Node_gw">
        <dc:Bounds x="250" y="10" width="50" height="50" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_sub" bpmnElement="Node_sub_off_label">
        <dc:Bounds x="350" y="10" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_end" bpmnElement="Node_end">
        <dc:Bounds x="500" y="10" width="36" height="36" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


@pytest.fixture
def coloured() -> ET.Element:
    """The stub document, run through the pass."""
    return ET.fromstring(apply(LAID_OUT))


def shape(root: ET.Element, element_id: str) -> ET.Element:
    """The BPMNShape drawing a given semantic element."""
    di = "http://www.omg.org/spec/BPMN/20100524/DI"
    return next(item for item in root.iter(f"{{{di}}}BPMNShape") if item.get("bpmnElement") == element_id)


def colors_of(root: ET.Element, element_id: str) -> tuple[str | None, str | None]:
    """The fill and stroke written onto an element, if any."""
    found = shape(root, element_id)
    return (
        found.get(f"{{{COLOR_NS}}}background-color"),
        found.get(f"{{{COLOR_NS}}}border-color"),
    )


@pytest.mark.parametrize("element_id", ["Node_start", "Node_end"])
def test_both_events_take_the_same_colour(coloured: ET.Element, element_id: str) -> None:
    """The entry and the exits are one kind of thing, and read as one."""
    assert colors_of(coloured, element_id) == EVENT


def test_a_collapsed_subprocess_is_its_own_colour(coloured: ET.Element) -> None:
    assert colors_of(coloured, "Node_sub_off_label") == SUBPROCESS


@pytest.mark.parametrize("element_id", ["Node_task", "Node_gw"])
def test_the_main_flow_keeps_the_default(coloured: ET.Element, element_id: str) -> None:
    """Colouring every box would say nothing; these are left to bpmn-js."""
    assert colors_of(coloured, element_id) == (None, None)


def test_the_attributes_are_the_ones_bpmn_js_reads(coloured: ET.Element) -> None:
    """The whole point is that the colour travels, so the namespace has to be right.

    ``getFillColor`` consults ``color:background-color`` before bpmn.io's older
    ``bioc:fill``. Writing anything else would colour nothing, silently.
    """
    assert COLOR_NS == "http://www.omg.org/spec/BPMN/non-normative/color/1.0"
    assert f"{{{COLOR_NS}}}background-color" in shape(coloured, "Node_start").attrib


def test_geometry_is_left_alone(coloured: ET.Element) -> None:
    """This pass is not the one that computes geometry, and must not become it."""
    bounds = shape(coloured, "Node_start").find("{http://www.omg.org/spec/DD/20100524/DC}Bounds")

    assert bounds is not None
    assert (bounds.get("width"), bounds.get("height")) == ("36", "36")


def test_a_document_without_diagram_interchange_survives() -> None:
    """Stage 2 always has DI by this point, but a pass that explodes without it is a trap."""
    semantic = '<?xml version="1.0" encoding="UTF-8"?>\n<definitions><startEvent id="a" /></definitions>\n'

    assert "startEvent" in apply(semantic)


def test_the_same_document_colours_the_same_way() -> None:
    """Stage 2 is deterministic, and this pass is part of it."""
    assert apply(LAID_OUT) == apply(LAID_OUT)
