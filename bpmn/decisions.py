"""Redrawing a decision so it carries its own question.

This is the **one** place in the project that computes geometry. Everywhere else
coordinates are the layouter's alone, and that is still the rule; what follows is
a stated exception to it, kept to one element type and one operation.

The reason it has to exist: BPMN puts a gateway's name on an *external* label,
and bpmn-js hard-codes the list of types whose label is external, so no styling
moves it inside the shape. The layouter then finds that label a collision-free
spot near the diamond -- below one decision, above the next -- and the diamond
itself is left carrying nothing but an ``X``. A reader has to pair each floating
question with the shape it belongs to.

So after the layout is computed, every gateway is redrawn: the diamond grows
about its own centre until the question fits inside it, the label is moved into
it, the ``X`` is dropped, and the arrows that met the old boundary are pushed out
to the new one.

The same pass fixes a second thing about how the layouter draws a decision: it
runs every branch out of the *same* vertex and separates them further along,
leaving two arrows sharing a line and three corners of the diamond unused. So a
branch whose target is below is sent out of the bottom point and one whose
target is above out of the top, each rebuilt as the two-segment L the layouter
itself draws for that case. See :func:`_spread`.

Nothing else in the document is touched -- other shapes, their labels, and every
connection that does not touch a gateway are written back as they arrived.

The size is a constant rather than a measurement of the text. Decisions that are
all one size read as one kind of thing, and the layouter leaves enough room
around a 50x50 gateway for :data:`DIAMOND` to fit: it spaces shapes by
``HORIZONTAL_GAP = 100`` and ``VERTICAL_GAP = 80`` and centres each one in its
row and column, so a gateway sharing a column with a task has about 125px of
clear space from its centre in each direction. If a question ever outgrows the
box, widen :data:`DIAMOND` rather than making the size depend on the wording.
"""

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from bpmn.document import BPMN_NS

BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"

ET.register_namespace("bpmndi", BPMNDI_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("di", DI_NS)

_WAYPOINT = f"{{{DI_NS}}}waypoint"

Point = tuple[float, float]

DIAMOND = (160.0, 120.0)
"""The width and height every decision is redrawn at, in place of the layouter's 50x50."""

_LABEL_FRACTION = 0.5
"""How much of the diamond the text may use.

Half of each side is the largest upright rectangle that fits inside a diamond, so
this is what keeps a wrapped question from crossing the slanted edges. Widening
it would let the first and last lines spill out of the shape.
"""

_LABEL_GAP = 6.0
"""How far a re-routed branch's label sits off its own line."""

_TOLERANCE = 1.0
"""Slack when comparing coordinates, so a shape level with another counts as level."""


def widen(xml: str) -> str:
    """Redraw every gateway in a laid-out document as a diamond holding its question.

    Args:
        xml: BPMN with complete diagram interchange, as the layouter returns it.

    Returns:
        The same document with each gateway resized about its centre, its label
        moved inside it, its ``X`` marker dropped, the arrows meeting it pushed
        out to the new boundary, and its branches sent out of the corner each is
        headed for. A document with no gateways, or with no diagram interchange,
        comes back unchanged in substance.

    Raises:
        xml.etree.ElementTree.ParseError: If the document is not well formed.
    """
    root = ET.fromstring(xml)  # noqa: S314  # our own layouter's output, not untrusted input

    gateways = _gateway_ids(root)
    resized: dict[str, tuple[Rect, Rect]] = {}
    for shape in root.iter(_di("BPMNShape")):
        element_id = shape.get("bpmnElement", "")
        if element_id not in gateways:
            continue
        sizes = _redraw(shape)
        if sizes is not None:
            resized[element_id] = sizes

    if resized:
        _reaim(root, resized)
        _spread(root, resized)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


@dataclass(frozen=True)
class Rect:
    """One ``dc:Bounds``."""

    x: float
    y: float
    width: float
    height: float

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    def about(self, width: float, height: float) -> "Rect":
        """The same centre, a different size."""
        centre_x, centre_y = self.centre
        return Rect(x=centre_x - width / 2, y=centre_y - height / 2, width=width, height=height)


def crosses(start: Point, end: Point, box: Rect, tolerance: float = 0.5) -> bool:
    """Whether a segment passes through a box's interior rather than skirting it.

    Exact for the orthogonal segments this project deals in, where a segment and
    its bounding box are the same thing. The tolerance is what lets a line run
    along a box's edge, which is what an arrow meeting one does.
    """
    return (
        max(start[0], end[0]) > box.x + tolerance
        and min(start[0], end[0]) < box.x + box.width - tolerance
        and max(start[1], end[1]) > box.y + tolerance
        and min(start[1], end[1]) < box.y + box.height - tolerance
    )


def _gateway_ids(root: ET.Element) -> frozenset[str]:
    """The ids of every gateway in the semantic tree.

    Matched on the tag ending in ``Gateway`` rather than on ``exclusiveGateway``
    alone: this stage only emits exclusive ones today, and a parallel one added
    later should be redrawn the same way rather than silently keep the old
    treatment.
    """
    return frozenset(
        element.get("id", "")
        for element in root.iter()
        if element.tag.startswith(f"{{{BPMN_NS}}}") and element.tag.endswith("Gateway") and element.get("id")
    )


def _redraw(shape: ET.Element) -> tuple[Rect, Rect] | None:
    """Resize one gateway's shape, move its label inside, and drop its marker.

    Args:
        shape: A ``bpmndi:BPMNShape`` standing for a gateway.

    Returns:
        The bounds before and after, or None if the shape carries none and there
        is nothing to redraw.
    """
    bounds = shape.find(_dc("Bounds"))
    old = _read(bounds)
    if bounds is None or old is None:
        return None

    new = old.about(*DIAMOND)
    _write(bounds, new)

    # The X promises a reader something the shape no longer has room to say, and
    # it is dropped in the file rather than hidden in our viewer's stylesheet:
    # BPMN allows an exclusive gateway to be drawn without the marker, so any
    # tool opening this document sees the same shape our page does.
    shape.attrib.pop("isMarkerVisible", None)

    label = shape.find(f"{_di('BPMNLabel')}/{_dc('Bounds')}")
    if label is not None:
        _write(label, new.about(new.width * _LABEL_FRACTION, new.height * _LABEL_FRACTION))

    return old, new


def _reaim(root: ET.Element, resized: dict[str, tuple[Rect, Rect]]) -> None:
    """Push every arrow that met a gateway's old boundary out to its new one.

    An endpoint left where it was would now sit well inside the diamond, with the
    arrowhead buried under the shape.

    Which end belongs to which shape is taken from the connection's own
    ``sourceRef`` and ``targetRef`` rather than guessed from the coordinates:
    the first waypoint is the source's, the last is the target's.
    """
    ends = {
        element.get("id", ""): (element.get("sourceRef", ""), element.get("targetRef", ""))
        for element in root.iter()
        if element.get("sourceRef") and element.get("targetRef")
    }

    for edge in root.iter(_di("BPMNEdge")):
        source, target = ends.get(edge.get("bpmnElement", ""), ("", ""))
        waypoints = edge.findall(_WAYPOINT)
        if len(waypoints) < 2:
            continue
        if source in resized:
            _push(waypoints[0], waypoints[1], *resized[source])
        if target in resized:
            _push(waypoints[-1], waypoints[-2], *resized[target])


def _push(waypoint: ET.Element, neighbour: ET.Element, old: Rect, new: Rect) -> None:
    """Move one endpoint from the old shape's boundary out to the new one.

    The endpoint sits on a vertex of the old diamond, which is the midpoint of
    one side of its bounding box, and the layouter's routing leaves the next
    waypoint square on from there. So the side it is on is whichever axis it is
    furthest from the centre on, and moving it along that axis alone keeps the
    segment orthogonal.

    Left alone if the push would take the endpoint past its neighbour: that
    happens only where a shape sits closer than the new half-width, and a
    cramped diagram is a better outcome than a backwards arrow.
    """
    point = _point(waypoint)
    beside = _point(neighbour)
    if point is None or beside is None:
        return

    centre_x, centre_y = old.centre
    across, down = point[0] - centre_x, point[1] - centre_y

    if abs(across) >= abs(down):
        moved = (centre_x + math.copysign(new.width / 2, across or 1.0), point[1])
        outward = math.copysign(1.0, across or 1.0) * (beside[0] - moved[0])
    else:
        moved = (point[0], centre_y + math.copysign(new.height / 2, down or 1.0))
        outward = math.copysign(1.0, down or 1.0) * (beside[1] - moved[1])

    if outward > 0:
        waypoint.set("x", _number(moved[0]))
        waypoint.set("y", _number(moved[1]))


def _spread(root: ET.Element, resized: dict[str, tuple[Rect, Rect]]) -> None:
    """Send each branch out of the corner of the diamond it is headed for.

    The layouter runs both branches out of the same vertex and separates them
    further along, which leaves two arrows sharing a line and three corners of the
    diamond unused. A branch whose target is below leaves from the bottom point
    instead, one whose target is above from the top, and the rest keep the route
    they were given -- running along a row is what the layouter is best at, and
    those already leave from the right point.

    Only the first branch to want a corner gets it. Two branches that both descend
    still leave from different points, because the second keeps the layouter's
    route out of the right vertex, which is all the separation is for.
    """
    ends = _connection_ends(root)
    boxes = _bounds_by_element(root)
    edges = {edge.get("bpmnElement", ""): edge for edge in root.iter(_di("BPMNEdge"))}
    obstacles = _obstacles(root, boxes)

    for gateway, (_, diamond) in resized.items():
        taken: set[str] = set()
        for flow, (source, target) in ends.items():
            corner = _corner(diamond, boxes[target]) if source == gateway and target in boxes else None
            if corner is None or corner in taken or flow not in edges:
                continue
            if _reroute(edges[flow], diamond, boxes[target], corner, {gateway, target}, obstacles):
                taken.add(corner)


def _corner(gateway: Rect, target: Rect) -> str | None:
    """Which point of the diamond a branch to this target should leave by, if any."""
    _, gateway_y = gateway.centre
    _, target_y = target.centre
    if target_y > gateway_y + _TOLERANCE:
        return "bottom"
    if target_y < gateway_y - _TOLERANCE:
        return "top"
    return None


def _reroute(
    edge: ET.Element, gateway: Rect, target: Rect, corner: str, ends: set[str], obstacles: dict[str, Rect]
) -> bool:
    """Rebuild one branch to leave the diamond by ``corner``.

    Returns:
        Whether the branch now leaves by that corner. False where the rebuild
        would have crossed a shape, in which case the layouter's route is left
        exactly as it was: a cramped diagram is better drawn its way than with an
        arrow through a box.
    """
    waypoints = edge.findall(_WAYPOINT)
    start = _vertex(gateway, corner)
    if len(waypoints) < 2:
        return False
    leaves_from = _point(waypoints[0])
    if leaves_from is None:
        return False
    if leaves_from == start:
        return True  # The layouter already sent it this way; leave it untouched.

    route = _route(start, gateway, target, corner)
    in_the_way = [rect for name, rect in obstacles.items() if name not in ends]
    segments = list(zip(route, route[1:], strict=False))
    if any(crosses(first, second, rect) for first, second in segments for rect in in_the_way):
        return False

    _write_route(edge, route)
    _move_label(edge, route)
    return True


def _route(start: Point, gateway: Rect, target: Rect, corner: str) -> list[Point]:
    """The two-segment L the layouter itself draws for a branch to one side.

    Straight out of the corner to the target's centre line, then across to the
    near side of it. A target sitting directly in line loses the bend and is met
    head on.
    """
    centre_x, _ = gateway.centre
    target_x, target_y = target.centre
    if target.x - _TOLERANCE <= centre_x <= target.x + target.width + _TOLERANCE:
        return [start, (centre_x, target.y if corner == "bottom" else target.y + target.height)]
    return [start, (centre_x, target_y), (target.x if target_x > centre_x else target.x + target.width, target_y)]


def _vertex(rect: Rect, corner: str) -> Point:
    """The bottom or top point of a diamond, which is the midpoint of that side of its box."""
    centre_x, _ = rect.centre
    return (centre_x, rect.y + rect.height) if corner == "bottom" else (centre_x, rect.y)


def _write_route(edge: ET.Element, route: list[Point]) -> None:
    """Replace an edge's waypoints, keeping them ahead of its label."""
    for waypoint in edge.findall(_WAYPOINT):
        edge.remove(waypoint)
    for index, (x, y) in enumerate(route):
        waypoint = ET.Element(_WAYPOINT)
        waypoint.set("x", _number(x))
        waypoint.set("y", _number(y))
        edge.insert(index, waypoint)


def _move_label(edge: ET.Element, route: list[Point]) -> None:
    """Bring a branch's label along to its new line.

    The layouter placed it against the route this replaced, and a ``Yes`` left
    behind beside nothing is worse than no label at all. It goes beside the middle
    of the first segment, which is the part of the arrow nearest the decision it
    answers.
    """
    bounds = edge.find(f"{_di('BPMNLabel')}/{_dc('Bounds')}")
    label = _read(bounds)
    if bounds is None or label is None:
        return

    (first_x, first_y), (second_x, second_y) = route[0], route[1]
    if first_x == second_x:  # A vertical run: the label sits to the right of it.
        placed = (first_x + _LABEL_GAP, (first_y + second_y) / 2 - label.height / 2)
    else:  # A horizontal one: above it.
        placed = ((first_x + second_x) / 2 - label.width / 2, first_y - label.height - _LABEL_GAP)
    _write(bounds, Rect(x=placed[0], y=placed[1], width=label.width, height=label.height))


def _connection_ends(root: ET.Element) -> dict[str, tuple[str, str]]:
    """Every connection's two ends, in the order the semantic tree declares them.

    That order is ``Edge.order`` within each gateway, because
    :func:`bpmn.semantics._in_branch_order` emitted the flows that way -- which is
    what makes "the first branch to want a corner gets it" mean the first branch
    the extractor listed.
    """
    return {
        element.get("id", ""): (element.get("sourceRef", ""), element.get("targetRef", ""))
        for element in root.iter()
        if element.get("sourceRef") and element.get("targetRef")
    }


def _bounds_by_element(root: ET.Element) -> dict[str, Rect]:
    """Every shape's bounds, by the element it draws. Read after the diamonds are resized."""
    found: dict[str, Rect] = {}
    for shape in root.iter(_di("BPMNShape")):
        rect = _read(shape.find(_dc("Bounds")))
        if rect is not None:
            found[shape.get("bpmnElement", "")] = rect
    return found


def _obstacles(root: ET.Element, boxes: dict[str, Rect]) -> dict[str, Rect]:
    """The shapes a re-routed branch must not be drawn through.

    Lanes and the pool are left out: they contain everything, so counting them
    would abandon every rebuild.
    """
    containers = {
        element.get("id", "")
        for element in root.iter()
        if element.tag in {f"{{{BPMN_NS}}}lane", f"{{{BPMN_NS}}}participant"}
    }
    return {name: rect for name, rect in boxes.items() if name not in containers}


def _read(bounds: ET.Element | None) -> Rect | None:
    """One ``dc:Bounds`` as a rectangle, or None if it is absent or malformed."""
    if bounds is None:
        return None
    try:
        return Rect(
            x=float(bounds.get("x", "")),
            y=float(bounds.get("y", "")),
            width=float(bounds.get("width", "")),
            height=float(bounds.get("height", "")),
        )
    except ValueError:
        return None


def _write(bounds: ET.Element, rect: Rect) -> None:
    bounds.set("x", _number(rect.x))
    bounds.set("y", _number(rect.y))
    bounds.set("width", _number(rect.width))
    bounds.set("height", _number(rect.height))


def _point(waypoint: ET.Element) -> tuple[float, float] | None:
    try:
        return float(waypoint.get("x", "")), float(waypoint.get("y", ""))
    except ValueError:
        return None


def _number(value: float) -> str:
    """A coordinate, written the way the layouter writes one: whole where it can be."""
    return str(int(value)) if value == int(value) else str(value)


def _di(tag: str) -> str:
    return f"{{{BPMNDI_NS}}}{tag}"


def _dc(tag: str) -> str:
    return f"{{{DC_NS}}}{tag}"
