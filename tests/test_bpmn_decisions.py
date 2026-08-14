"""Redrawing a decision after the layout has been computed.

The one file in the suite that asserts coordinates, because this is the one
place the project produces any. Everything else takes the layouter's geometry as
given and checks what it is *told* about the diagram, not where things sit.

The documents here are written by hand rather than laid out for real: the input
this module has to survive is BPMN with complete diagram interchange, and a
hand-written one is the only way to put a shape exactly where a case needs it.
The real layouter's output is exercised in ``tests/test_stage2_integration.py``.
"""

import xml.etree.ElementTree as ET

import pytest

from bpmn.decisions import DIAMOND, widen

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
NS = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS}

Rect = tuple[float, float, float, float]
Point = tuple[float, float]

# One gateway at (911, 396), fed from the left, leaving to the right and downward
# -- the shape of every decision the real layouter produces. The task before it
# and the box below it are there to prove they come back untouched.
LAID_OUT = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_test">
  <bpmn:process id="Process_test" isExecutable="false">
    <bpmn:startEvent id="Node_start" name="PEF received" />
    <bpmn:task id="Node_transcribe" name="Transcribe the PEF" />
    <bpmn:exclusiveGateway id="Node_gw" name="Is the diagnosis code off-label?" />
    <bpmn:task id="Node_next" name="Check for a duplicate" />
    <bpmn:subProcess id="Node_sub_off_label" name="Off-Label Review" />
    <bpmn:sequenceFlow id="Flow_in" sourceRef="Node_transcribe" targetRef="Node_gw" />
    <bpmn:sequenceFlow id="Flow_on" sourceRef="Node_gw" targetRef="Node_next" name="not off-label" />
    <bpmn:sequenceFlow id="Flow_down" sourceRef="Node_gw" targetRef="Node_sub_off_label" name="off-label" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_test">
    <bpmndi:BPMNPlane id="BPMNPlane_test" bpmnElement="Process_test">
      <bpmndi:BPMNShape id="Shape_start" bpmnElement="Node_start">
        <dc:Bounds x="150" y="378" width="36" height="36" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="136" y="419" width="65" height="28" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_transcribe" bpmnElement="Node_transcribe">
        <dc:Bounds x="286" y="356" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_gw" bpmnElement="Node_gw" isMarkerVisible="true">
        <dc:Bounds x="886" y="371" width="50" height="50" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="868" y="426" width="87" height="42" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_next" bpmnElement="Node_next">
        <dc:Bounds x="1036" y="356" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_sub" bpmnElement="Node_sub_off_label">
        <dc:Bounds x="861" y="596" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Edge_in" bpmnElement="Flow_in">
        <di:waypoint x="386" y="396" />
        <di:waypoint x="886" y="396" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Edge_on" bpmnElement="Flow_on">
        <di:waypoint x="936" y="396" />
        <di:waypoint x="1036" y="396" />
        <bpmndi:BPMNLabel>
          <dc:Bounds x="950" y="360" width="70" height="28" />
        </bpmndi:BPMNLabel>
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Edge_down" bpmnElement="Flow_down">
        <di:waypoint x="911" y="421" />
        <di:waypoint x="911" y="596" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""


@pytest.fixture
def redrawn() -> ET.Element:
    return ET.fromstring(widen(LAID_OUT))


def bounds_of(diagram: ET.Element, element_id: str) -> Rect:
    """One shape's bounds, by the element it draws."""
    shape = next(item for item in diagram.iter(f"{{{BPMNDI_NS}}}BPMNShape") if item.get("bpmnElement") == element_id)
    box = shape.find("dc:Bounds", NS)
    assert box is not None
    return tuple(float(box.get(key, 0)) for key in ("x", "y", "width", "height"))  # type: ignore[return-value]


def label_of(diagram: ET.Element, element_id: str) -> Rect | None:
    """One shape's label bounds, or None if it carries no label."""
    shape = next(item for item in diagram.iter(f"{{{BPMNDI_NS}}}BPMNShape") if item.get("bpmnElement") == element_id)
    box = shape.find("bpmndi:BPMNLabel/dc:Bounds", NS)
    if box is None:
        return None
    return tuple(float(box.get(key, 0)) for key in ("x", "y", "width", "height"))  # type: ignore[return-value]


def waypoints_of(diagram: ET.Element, element_id: str) -> list[Point]:
    edge = next(item for item in diagram.iter(f"{{{BPMNDI_NS}}}BPMNEdge") if item.get("bpmnElement") == element_id)
    return [(float(point.get("x", 0)), float(point.get("y", 0))) for point in edge.findall("di:waypoint", NS)]


def centre(rect: Rect) -> Point:
    return rect[0] + rect[2] / 2, rect[1] + rect[3] / 2


def test_the_diamond_grows_about_its_own_centre(redrawn: ET.Element) -> None:
    """Moving it would break every edge the layouter routed to reach it."""
    box = bounds_of(redrawn, "Node_gw")

    assert (box[2], box[3]) == DIAMOND
    assert centre(box) == (911, 396)


def test_the_question_is_moved_inside_the_diamond(redrawn: ET.Element) -> None:
    """It sat below the shape, where a reader has to work out which decision it belongs to."""
    box = bounds_of(redrawn, "Node_gw")
    label = label_of(redrawn, "Node_gw")

    assert label is not None
    assert centre(label) == centre(box)
    assert label[0] >= box[0] and label[0] + label[2] <= box[0] + box[2]
    assert label[1] >= box[1] and label[1] + label[3] <= box[1] + box[3]


def test_the_label_stays_within_the_slanted_edges(redrawn: ET.Element) -> None:
    """The biggest upright box inside a diamond is half of each side; wider text would cross the outline."""
    box = bounds_of(redrawn, "Node_gw")
    label = label_of(redrawn, "Node_gw")

    assert label is not None
    assert (label[2], label[3]) == (box[2] / 2, box[3] / 2)


def test_the_marker_is_dropped(redrawn: ET.Element) -> None:
    """The X is removed in the file, not hidden in our stylesheet: BPMN permits a gateway without it."""
    shape = next(item for item in redrawn.iter(f"{{{BPMNDI_NS}}}BPMNShape") if item.get("bpmnElement") == "Node_gw")

    assert "isMarkerVisible" not in shape.attrib


def test_an_arrow_arriving_meets_the_new_boundary(redrawn: ET.Element) -> None:
    """Left where it was, the arrowhead would be buried well inside the shape."""
    box = bounds_of(redrawn, "Node_gw")

    assert waypoints_of(redrawn, "Flow_in")[-1] == (box[0], 396)


def test_an_arrow_leaving_sideways_starts_at_the_new_boundary(redrawn: ET.Element) -> None:
    box = bounds_of(redrawn, "Node_gw")

    assert waypoints_of(redrawn, "Flow_on")[0] == (box[0] + box[2], 396)


def test_an_arrow_leaving_downward_starts_at_the_new_boundary(redrawn: ET.Element) -> None:
    """The axis is whichever one the endpoint was furthest out on, so the segment stays square."""
    box = bounds_of(redrawn, "Node_gw")

    assert waypoints_of(redrawn, "Flow_down")[0] == (911, box[1] + box[3])


def test_the_waypoints_in_between_are_left_alone(redrawn: ET.Element) -> None:
    assert waypoints_of(redrawn, "Flow_in")[0] == (386, 396)
    assert waypoints_of(redrawn, "Flow_on")[-1] == (1036, 396)


def test_every_other_shape_keeps_the_geometry_the_layouter_gave_it(redrawn: ET.Element) -> None:
    """Only decisions are redrawn. A task moving would be this module exceeding its remit."""
    assert bounds_of(redrawn, "Node_transcribe") == (286, 356, 100, 80)
    assert bounds_of(redrawn, "Node_next") == (1036, 356, 100, 80)
    assert bounds_of(redrawn, "Node_sub_off_label") == (861, 596, 100, 80)
    assert bounds_of(redrawn, "Node_start") == (150, 378, 36, 36)


def test_an_external_label_that_is_not_a_decisions_is_left_where_it_was(redrawn: ET.Element) -> None:
    """An event's name belongs outside it; only a gateway's had nowhere useful to go."""
    assert label_of(redrawn, "Node_start") == (136, 419, 65, 28)


def test_a_flow_label_is_left_where_it_was(redrawn: ET.Element) -> None:
    """The branch wording is the arrow's, and the layouter already placed it clear of everything."""
    edge = next(item for item in redrawn.iter(f"{{{BPMNDI_NS}}}BPMNEdge") if item.get("bpmnElement") == "Flow_on")
    box = edge.find("bpmndi:BPMNLabel/dc:Bounds", NS)

    assert box is not None
    assert box.get("x") == "950"


def test_an_unnamed_gateway_gains_no_label(redrawn: ET.Element) -> None:
    """There is nothing to put inside it, and an empty label box would draw nothing."""
    unnamed = widen(
        LAID_OUT.replace(' name="Is the diagnosis code off-label?"', "").replace(
            """<bpmndi:BPMNLabel>
          <dc:Bounds x="868" y="426" width="87" height="42" />
        </bpmndi:BPMNLabel>""",
            "",
        )
    )

    assert label_of(ET.fromstring(unnamed), "Node_gw") is None
    assert bounds_of(ET.fromstring(unnamed), "Node_gw")[2:] == DIAMOND


def test_an_endpoint_is_left_alone_when_the_push_would_pass_its_neighbour() -> None:
    """A cramped diagram degrades to the old drawing rather than to a backwards arrow."""
    cramped = LAID_OUT.replace('<di:waypoint x="1036" y="396" />', '<di:waypoint x="950" y="396" />')

    assert waypoints_of(ET.fromstring(widen(cramped)), "Flow_on")[0] == (936, 396)


# ---- branches leaving by their own corner ------------------------------------
#
# Assembled rather than written out, because these cases are about where one
# shape sits relative to another and a wall of XML hides that. The gateway is
# always the 50x50 the layouter produces, at (886, 371), so it widens to
# (831, 336, 160, 120) with its centre at (911, 396) and its bottom point at
# (911, 456) -- the numbers the assertions below are written against.

GATEWAY = (886.0, 371.0, 50.0, 50.0)


def assemble(shapes: dict[str, Rect], flows: dict[str, tuple[str, str, list[Point]]], labelled: str = "") -> str:
    """A laid-out document with one gateway, some boxes, and some routed flows."""
    semantic = "".join(
        f'<bpmn:{"exclusiveGateway" if name == "Node_gw" else "task"} id="{name}" name="{name}" />' for name in shapes
    )
    semantic += "".join(
        f'<bpmn:sequenceFlow id="{flow}" sourceRef="{source}" targetRef="{target}" name="Yes" />'
        for flow, (source, target, _) in flows.items()
    )
    drawn = "".join(
        f'<bpmndi:BPMNShape id="Shape_{name}" bpmnElement="{name}">'
        f'<dc:Bounds x="{box[0]}" y="{box[1]}" width="{box[2]}" height="{box[3]}" />'
        f"</bpmndi:BPMNShape>"
        for name, box in shapes.items()
    )
    drawn += "".join(
        f'<bpmndi:BPMNEdge id="Edge_{flow}" bpmnElement="{flow}">'
        + "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in points)
        + (
            '<bpmndi:BPMNLabel><dc:Bounds x="1000" y="1000" width="30" height="20" /></bpmndi:BPMNLabel>'
            if flow == labelled
            else ""
        )
        + "</bpmndi:BPMNEdge>"
        for flow, (_, _, points) in flows.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" xmlns:bpmndi="{BPMNDI_NS}" xmlns:dc="{DC_NS}"'
        f' xmlns:di="{DI_NS}" id="Definitions_test">'
        f'<bpmn:process id="Process_test">{semantic}</bpmn:process>'
        f'<bpmndi:BPMNDiagram id="D"><bpmndi:BPMNPlane id="P" bpmnElement="Process_test">{drawn}'
        "</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
    )


def shared_exit(labelled: str = "") -> str:
    """Both branches out of the right vertex: one carrying on, one dropping to a box below."""
    return assemble(
        {
            "Node_gw": GATEWAY,
            "Node_on": (1181.0, 356.0, 100.0, 80.0),
            "Node_below": (1036.0, 516.0, 100.0, 80.0),
        },
        {
            "Flow_on": ("Node_gw", "Node_on", [(936.0, 396.0), (1181.0, 396.0)]),
            "Flow_down": ("Node_gw", "Node_below", [(936.0, 396.0), (1086.0, 396.0), (1086.0, 516.0)]),
        },
        labelled,
    )


def test_a_branch_to_a_box_below_leaves_by_the_bottom_point() -> None:
    """Not the right vertex the layouter used, which it shared with the branch carrying on."""
    redrawn = ET.fromstring(widen(shared_exit()))

    assert waypoints_of(redrawn, "Flow_down") == [(911, 456), (911, 556), (1036, 556)]


def test_a_branch_carrying_on_across_the_row_is_left_as_the_layouter_routed_it() -> None:
    """Running along a row is what it is best at, and that branch already leaves by its own point."""
    redrawn = ET.fromstring(widen(shared_exit()))

    assert waypoints_of(redrawn, "Flow_on") == [(991, 396), (1181, 396)]


def test_the_two_branches_no_longer_start_at_the_same_point() -> None:
    """The whole ask: one arrow per corner, not two sharing a line."""
    redrawn = ET.fromstring(widen(shared_exit()))

    assert waypoints_of(redrawn, "Flow_down")[0] != waypoints_of(redrawn, "Flow_on")[0]


def test_a_branch_to_a_box_above_leaves_by_the_top_point() -> None:
    redrawn = ET.fromstring(
        widen(
            assemble(
                {"Node_gw": GATEWAY, "Node_above": (1036.0, 136.0, 100.0, 80.0)},
                {"Flow_up": ("Node_gw", "Node_above", [(936.0, 396.0), (1086.0, 396.0), (1086.0, 216.0)])},
            )
        )
    )

    assert waypoints_of(redrawn, "Flow_up") == [(911, 336), (911, 176), (1036, 176)]


def test_a_box_directly_below_is_met_head_on() -> None:
    """No bend to draw when the target is already in line with the point it leaves by."""
    redrawn = ET.fromstring(
        widen(
            assemble(
                {"Node_gw": GATEWAY, "Node_below": (861.0, 516.0, 100.0, 80.0)},
                {"Flow_down": ("Node_gw", "Node_below", [(936.0, 396.0), (1000.0, 396.0), (1000.0, 516.0)])},
            )
        )
    )

    assert waypoints_of(redrawn, "Flow_down") == [(911, 456), (911, 516)]


def test_a_branch_the_layouter_already_sent_that_way_is_untouched() -> None:
    """It got there first; rebuilding would only risk moving an arrow that was already right."""
    redrawn = ET.fromstring(
        widen(
            assemble(
                {"Node_gw": GATEWAY, "Node_below": (1036.0, 516.0, 100.0, 80.0)},
                # Already out of the bottom vertex, which _reaim pushes to (911, 456).
                {"Flow_down": ("Node_gw", "Node_below", [(911.0, 421.0), (911.0, 556.0), (1036.0, 556.0)])},
            )
        )
    )

    assert waypoints_of(redrawn, "Flow_down") == [(911, 456), (911, 556), (1036, 556)]


def test_a_rebuild_that_would_cross_a_box_is_abandoned() -> None:
    """A cramped diagram is better drawn the layouter's way than with an arrow through a box."""
    redrawn = ET.fromstring(
        widen(
            assemble(
                {
                    "Node_gw": GATEWAY,
                    "Node_below": (1036.0, 516.0, 100.0, 80.0),
                    "Node_in_the_way": (861.0, 476.0, 100.0, 80.0),
                },
                {"Flow_down": ("Node_gw", "Node_below", [(936.0, 396.0), (1086.0, 396.0), (1086.0, 516.0)])},
            )
        )
    )

    assert waypoints_of(redrawn, "Flow_down") == [(991, 396), (1086, 396), (1086, 516)]


def test_only_the_first_branch_wanting_a_corner_gets_it() -> None:
    """Two branches both heading down still leave by different points, which is what this is for."""
    redrawn = ET.fromstring(
        widen(
            assemble(
                {
                    "Node_gw": GATEWAY,
                    "Node_first": (1036.0, 516.0, 100.0, 80.0),
                    "Node_second": (1236.0, 516.0, 100.0, 80.0),
                },
                {
                    "Flow_first": ("Node_gw", "Node_first", [(936.0, 396.0), (1086.0, 396.0), (1086.0, 516.0)]),
                    "Flow_second": ("Node_gw", "Node_second", [(936.0, 396.0), (1286.0, 396.0), (1286.0, 516.0)]),
                },
            )
        )
    )

    assert waypoints_of(redrawn, "Flow_first")[0] == (911, 456)
    assert waypoints_of(redrawn, "Flow_second")[0] == (991, 396)


def test_a_rebuilt_branch_takes_its_label_with_it() -> None:
    """A 'Yes' left beside the route this replaced is worse than no label at all."""
    edge = next(
        item
        for item in ET.fromstring(widen(shared_exit(labelled="Flow_down"))).iter(f"{{{BPMNDI_NS}}}BPMNEdge")
        if item.get("bpmnElement") == "Flow_down"
    )
    box = edge.find("bpmndi:BPMNLabel/dc:Bounds", NS)

    assert box is not None
    # Beside the middle of the vertical run out of the bottom point, (911, 456) to (911, 556).
    assert (box.get("x"), box.get("y")) == ("917", "496")


def test_a_document_with_no_decisions_keeps_every_coordinate() -> None:
    plain = LAID_OUT.replace("bpmn:exclusiveGateway", "bpmn:task")
    redrawn = ET.fromstring(widen(plain))

    assert bounds_of(redrawn, "Node_gw") == (886, 371, 50, 50)
    assert waypoints_of(redrawn, "Flow_in")[-1] == (886, 396)


def test_identical_input_yields_identical_output() -> None:
    """Stage 2's headline guarantee has to survive the pass that follows it."""
    assert widen(LAID_OUT) == widen(LAID_OUT)
