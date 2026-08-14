"""Stage 2 against the real layouter, on the real enrollment graph.

The only tests that shell out to Node, and the only ones that can check what the
stage actually promises. Everything asserted here is read back out of the
written file rather than from an internal model, because the geometry is not
ours: `bpmn-auto-layout` produces it, and the file is the only place we and a
renderer see the same thing.

That makes this suite the regression guard on the pinned pre-release. If a later
version of the layouter stops honouring lanes or starts drawing edges through
boxes, these are what notice.

Skipped, not failed, where Node is absent -- the rest of the suite still runs.
"""

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipelines.stage2 import DIAGRAM_FILENAME, run
from tests.conftest import ENROLLMENT_DIR, requires_node

pytestmark = requires_node

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
NS = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS}

ENROLLMENT_LANES = ["HCP", "CM360", "PSM", "QRAL", "JCRM"]

Rect = tuple[float, float, float, float]


@pytest.fixture(scope="module")
def diagram(tmp_path_factory: pytest.TempPathFactory) -> ET.Element:
    """Enrollment laid out by the real layouter. Module-scoped: it costs a Node run."""
    root = tmp_path_factory.mktemp("processes-root") / "processes"
    shutil.copytree(ENROLLMENT_DIR, root / "enrollment")
    return ET.fromstring(run("enrollment", root).read_text(encoding="utf-8"))


def bounds_of(diagram: ET.Element) -> dict[str, Rect]:
    """Every shape's bounds, by the element it draws."""
    found: dict[str, Rect] = {}
    for shape in diagram.iter(f"{{{BPMNDI_NS}}}BPMNShape"):
        box = shape.find("dc:Bounds", NS)
        assert box is not None, shape.get("bpmnElement")
        element = shape.get("bpmnElement")
        assert element is not None
        found[element] = tuple(float(box.get(key, 0)) for key in ("x", "y", "width", "height"))  # type: ignore[assignment]
    return found


def waypoints_of(diagram: ET.Element) -> dict[str, list[tuple[float, float]]]:
    """Every edge's polyline, by the element it draws."""
    return {
        str(edge.get("bpmnElement")): [
            (float(point.get("x", 0)), float(point.get("y", 0))) for point in edge.findall("di:waypoint", NS)
        ]
        for edge in diagram.iter(f"{{{BPMNDI_NS}}}BPMNEdge")
    }


def contains(outer: Rect, inner: Rect, tolerance: float = 0.5) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (
        ix >= ox - tolerance
        and iy >= oy - tolerance
        and ix + iw <= ox + ow + tolerance
        and iy + ih <= oy + oh + tolerance
    )


def crosses(start: tuple[float, float], end: tuple[float, float], box: Rect, tolerance: float = 0.5) -> bool:
    """Whether a segment passes through a box's interior rather than skirting it."""
    x, y, width, height = box
    return (
        max(start[0], end[0]) > x + tolerance
        and min(start[0], end[0]) < x + width - tolerance
        and max(start[1], end[1]) > y + tolerance
        and min(start[1], end[1]) < y + height - tolerance
    )


def test_the_five_enrollment_lanes_are_drawn(diagram: ET.Element) -> None:
    """Only the actors that own a node, in metadata.yaml declaration order."""
    lanes = diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)

    assert [lane.get("name") for lane in lanes] == ENROLLMENT_LANES


def test_every_lane_has_a_shape(diagram: ET.Element) -> None:
    """A lane with no bounds is a swimlane the renderer does not draw."""
    drawn = bounds_of(diagram)

    for lane in diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS):
        assert lane.get("id") in drawn, lane.get("name")


def test_every_box_sits_inside_its_actors_lane(diagram: ET.Element) -> None:
    """The definition of done: a box is in the lane of whoever performs it."""
    drawn = bounds_of(diagram)
    offences = [
        (ref.text, lane.get("name"))
        for lane in diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)
        for ref in lane.findall("bpmn:flowNodeRef", NS)
        if not contains(drawn[str(lane.get("id"))], drawn[str(ref.text)])
    ]

    assert offences == []


def test_the_lanes_tile_the_pool(diagram: ET.Element) -> None:
    """Contiguous bands, or the diagram shows seams between the lanes."""
    drawn = bounds_of(diagram)
    participant = diagram.find("bpmn:collaboration/bpmn:participant", NS)
    assert participant is not None
    pool = drawn[str(participant.get("id"))]

    bands = sorted(
        (drawn[str(lane.get("id"))] for lane in diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)),
        key=lambda band: band[1],
    )
    assert bands[0][1] == pool[1]
    for upper, lower in zip(bands, bands[1:], strict=False):
        assert upper[1] + upper[3] == lower[1]
    assert bands[-1][1] + bands[-1][3] == pool[1] + pool[3]


def test_every_shape_has_positive_bounds(diagram: ET.Element) -> None:
    for element, (_, _, width, height) in bounds_of(diagram).items():
        assert width > 0 and height > 0, element


def test_every_edge_has_at_least_two_waypoints(diagram: ET.Element) -> None:
    routes = waypoints_of(diagram)

    assert routes
    for element, points in routes.items():
        assert len(points) >= 2, element


def test_no_edge_passes_through_an_unrelated_box(diagram: ET.Element) -> None:
    """The other half of the definition of done, and the reason for this layouter."""
    drawn = bounds_of(diagram)
    lanes = {str(lane.get("id")) for lane in diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)}
    participant = diagram.find("bpmn:collaboration/bpmn:participant", NS)
    assert participant is not None
    containers = lanes | {str(participant.get("id"))}

    ends = {}
    process = diagram.find("bpmn:process", NS)
    assert process is not None
    for child in process:
        tag = child.tag.split("}")[-1]
        if tag in {"sequenceFlow", "association"}:
            ends[str(child.get("id"))] = {child.get("sourceRef"), child.get("targetRef")}

    offences = [
        (element, node_id)
        for element, points in waypoints_of(diagram).items()
        for start, end in zip(points, points[1:], strict=False)
        for node_id, box in drawn.items()
        if node_id not in containers and node_id not in ends.get(element, set()) and crosses(start, end, box)
    ]

    assert offences == []


def test_every_semantic_element_is_drawn(diagram: ET.Element) -> None:
    """DI missing for an element means it silently does not appear."""
    drawn = set(bounds_of(diagram)) | set(waypoints_of(diagram))
    process = diagram.find("bpmn:process", NS)
    assert process is not None
    expected = {str(child.get("id")) for child in process if child.tag.split("}")[-1] != "laneSet"}
    expected |= {str(lane.get("id")) for lane in diagram.findall("bpmn:process/bpmn:laneSet/bpmn:lane", NS)}

    assert expected <= drawn


def test_the_annotation_and_its_association_are_drawn(diagram: ET.Element) -> None:
    """Artifacts are the easiest thing for a layouter to drop."""
    drawn = set(bounds_of(diagram)) | set(waypoints_of(diagram))
    annotation = diagram.find("bpmn:process/bpmn:textAnnotation", NS)
    association = diagram.find("bpmn:process/bpmn:association", NS)

    assert annotation is not None and str(annotation.get("id")) in drawn
    assert association is not None and str(association.get("id")) in drawn


def test_identical_input_yields_byte_identical_output(tmp_path: Path) -> None:
    """The stage's headline guarantee, end to end through the real layouter."""
    root = tmp_path / "processes"
    shutil.copytree(ENROLLMENT_DIR, root / "enrollment")

    first = run("enrollment", root).read_bytes()
    second = run("enrollment", root).read_bytes()

    assert first == second


def test_the_diagram_is_written_where_stage_three_will_look(tmp_path: Path) -> None:
    root = tmp_path / "processes"
    shutil.copytree(ENROLLMENT_DIR, root / "enrollment")

    assert run("enrollment", root) == root / "enrollment" / "outputs" / DIAGRAM_FILENAME
