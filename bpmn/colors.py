"""Colouring the laid-out diagram, in the file rather than in a stylesheet.

BPMN carries colour as two diagram-interchange attributes in a non-normative
namespace the spec reserves for it, and bpmn-js reads them:
``getFillColor`` consults ``color:background-color`` first, then bpmn.io's older
``bioc:fill``, then a default. Writing the ``color:`` pair here means the page,
Camunda Modeler and bpmn.io all draw the same diagram, which a page stylesheet
could never achieve -- a colleague opening ``diagram.bpmn`` would see plain
black and white.

This is deliberately **not** in :mod:`bpmn.decisions`. That module is the one
place in the project that computes geometry, and it earns the exception by being
only that; colour is a different concern that happens to be written to the same
elements.

Only events and collapsed subprocesses are coloured. Tasks and gateways keep
bpmn-js's defaults, because the point is to make the entry, the exit and the
handed-off work findable at a glance -- colouring everything would say nothing.
Fills are pale and strokes saturated so that black label text stays readable on
top of them.
"""

import xml.etree.ElementTree as ET

BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
COLOR_NS = "http://www.omg.org/spec/BPMN/non-normative/color/1.0"

ET.register_namespace("color", COLOR_NS)

FILL = "background-color"
STROKE = "border-color"

EVENT = ("#E3F3E7", "#1A1628")
"""Start and end alike: the process's entry and its exits, in the same colour."""

SUBPROCESS = ("#EEEDF3", "#3A3650")
"""Work the source hands off, drawn as one box."""

_BY_TAG: dict[str, tuple[str, str]] = {
    "startEvent": EVENT,
    "endEvent": EVENT,
    "subProcess": SUBPROCESS,
}


def apply(xml: str) -> str:
    """Write fill and stroke onto every element type this project colours.

    Args:
        xml: BPMN with diagram interchange, as the layouter returns it.

    Returns:
        The same document with ``color:`` attributes on the shapes named in
        :data:`_BY_TAG`. A document with no diagram interchange, or none of
        those elements, comes back unchanged in substance.

    Raises:
        xml.etree.ElementTree.ParseError: If the document is not well formed.
    """
    root = ET.fromstring(xml)  # noqa: S314  # our own layouter's output, not untrusted input

    wanted = _colors_by_element(root)
    for shape in root.iter(f"{{{BPMNDI_NS}}}BPMNShape"):
        colors = wanted.get(shape.get("bpmnElement", ""))
        if colors is None:
            continue
        fill, stroke = colors
        shape.set(f"{{{COLOR_NS}}}{FILL}", fill)
        shape.set(f"{{{COLOR_NS}}}{STROKE}", stroke)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _colors_by_element(root: ET.Element) -> dict[str, tuple[str, str]]:
    """Which colours each semantic element should be drawn in, by its id.

    Read from the semantic tree rather than guessed from the shape, because the
    diagram-interchange element says only what it *draws*, never what it *is*.
    """
    found: dict[str, tuple[str, str]] = {}
    for element in root.iter():
        colors = _BY_TAG.get(element.tag.rsplit("}", 1)[-1])
        element_id = element.get("id", "")
        if colors is not None and element_id:
            found[element_id] = colors
    return found
