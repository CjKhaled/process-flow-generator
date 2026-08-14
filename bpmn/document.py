"""Writing the semantic ``.bpmn`` document -- the part that has no coordinates.

This stage deliberately emits **no diagram interchange at all**. Geometry is
`bpmn-auto-layout`'s job, and it discards any existing DI before generating its
own, so a plane written here would be computed and then thrown away.

What still has to be right is the semantic tree, and the trap there is that
**child order is significant and no schema checks it**. ``tProcess`` is a
sequence -- lane sets, then flow elements, then artifacts -- so a
``textAnnotation`` emitted next to the tasks is out of order even though every
element is present. The usual symptom is a file that parses and opens blank.

Order matters for a second reason here: the layouter breaks ties on BPMN
declaration order, so the sequence :mod:`bpmn.semantics` chose is the one thing
that steers the drawing. This module writes it out unchanged and adds no
ordering of its own.
"""

import xml.etree.ElementTree as ET

from bpmn.semantics import Definitions

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
TARGET_NS = "http://process-flow-generator/bpmn"

ET.register_namespace("bpmn", BPMN_NS)


def render(definitions: Definitions) -> str:
    """Write the semantic BPMN document, ready to be laid out.

    Args:
        definitions: What each element is.

    Returns:
        The XML, ending in a newline. Identical input yields identical output:
        every id comes from the IR and nothing here consults a clock, a
        random source, or an unordered collection.
    """
    root = ET.Element(
        _bpmn("definitions"),
        {"id": f"Definitions_{definitions.process_name}", "targetNamespace": TARGET_NS},
    )
    _collaboration(root, definitions)
    _process(root, definitions)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _collaboration(root: ET.Element, definitions: Definitions) -> None:
    """The pool, and the process it stands for.

    A collaboration rather than a bare process because the layouter selects one
    when present, and a pool is what gives the lanes something to sit inside.
    """
    collaboration = ET.SubElement(root, _bpmn("collaboration"), {"id": definitions.collaboration_id})
    ET.SubElement(
        collaboration,
        _bpmn("participant"),
        {
            "id": definitions.participant_id,
            "name": definitions.display_name,
            "processRef": definitions.process_id,
        },
    )


def _process(root: ET.Element, definitions: Definitions) -> None:
    """The lanes, the flow elements, then the artifacts -- in that order."""
    process = ET.SubElement(root, _bpmn("process"), {"id": definitions.process_id, "isExecutable": "false"})

    lane_set = ET.SubElement(process, _bpmn("laneSet"), {"id": f"LaneSet_{definitions.process_id}"})
    for lane in definitions.lanes:
        element = ET.SubElement(lane_set, _bpmn("lane"), {"id": lane.element_id, "name": lane.actor})
        for flow_node_id in lane.flow_node_ids:
            ET.SubElement(element, _bpmn("flowNodeRef")).text = flow_node_id

    for node in definitions.flow_nodes:
        ET.SubElement(process, _bpmn(node.kind.value), {"id": node.element_id, "name": node.name})
    for flow in definitions.flows:
        attributes = {"id": flow.element_id, "sourceRef": flow.source_id, "targetRef": flow.target_id}
        if flow.name:
            attributes["name"] = flow.name
        ET.SubElement(process, _bpmn("sequenceFlow"), attributes)

    # Artifacts come after every flow element, per the tProcess sequence.
    for annotation in definitions.annotations:
        element = ET.SubElement(process, _bpmn("textAnnotation"), {"id": annotation.element_id})
        ET.SubElement(element, _bpmn("text")).text = annotation.text
    for association in definitions.associations:
        ET.SubElement(
            process,
            _bpmn("association"),
            {
                "id": association.element_id,
                "sourceRef": association.source_id,
                "targetRef": association.target_id,
                "associationDirection": "None",
            },
        )


def _bpmn(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"
