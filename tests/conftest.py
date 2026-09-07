"""Shared fixtures."""

import shutil
from pathlib import Path

import pytest

from bpmn.autolayout import Layouter
from ir.models import EdgeType, NodeType, ProcessGraph
from ir.process_config import ProcessConfig, load_process_config
from ir.skeleton import Skeleton, load_skeleton
from render.assets import ViewerAssets
from tests.builders import branch, edge, graph, node

REPO_ROOT = Path(__file__).resolve().parent.parent
ENROLLMENT_DIR = REPO_ROOT / "processes" / "enrollment"


def has_node() -> bool:
    """Whether the real layouter can be run here."""
    return shutil.which("node") is not None and (REPO_ROOT / "js" / "node_modules").is_dir()


requires_node = pytest.mark.skipif(not has_node(), reason="needs node and `npm ci --prefix js`")


def echo_layouter(xml: str) -> str:
    """A stand-in for the layouter, so the stage can be tested without Node.

    Returns the document unchanged. That is deliberately not a fake layout: no
    assertion outside the integration test should depend on geometry, because
    geometry is the layouter's to produce and inventing a plausible-looking
    version here would only test the fake. What this does exercise is everything
    on either side of the subprocess -- the semantic document going in and the
    file being written out.
    """
    return xml


LAID_OUT_WITH_A_DECISION = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" id="Definitions_stub">
  <bpmn:process id="Process_stub">
    <bpmn:task id="Node_task" name="Transcribe the PEF" />
    <bpmn:exclusiveGateway id="Node_gw" name="Is it off-label?" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_stub">
    <bpmndi:BPMNPlane id="BPMNPlane_stub" bpmnElement="Process_stub">
      <bpmndi:BPMNShape id="Shape_task" bpmnElement="Node_task">
        <dc:Bounds x="10" y="10" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Shape_gw" bpmnElement="Node_gw" isMarkerVisible="true">
        <dc:Bounds x="310" y="25" width="50" height="50" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
"""
"""What a layouter hands back, in miniature.

Enough diagram interchange to tell a redrawn decision from an untouched task, for
the stages that run :mod:`bpmn.decisions` over whatever the layouter returned.
"""


def decision_layouter(xml: str) -> str:  # noqa: ARG001  # the Layouter protocol names the parameter
    """A stand-in that hands back a document with one gateway already placed."""
    return LAID_OUT_WITH_A_DECISION


@pytest.fixture
def layouter() -> Layouter:
    """The pass-through layouter, as the injectable dependency."""
    return echo_layouter


@pytest.fixture
def viewer_assets() -> ViewerAssets:
    """Stand-ins for the bpmn-js dist files.

    Short strings rather than the real 300 KB, so the page tests neither need
    ``npm ci`` nor drown the thing under test in vendor code. What matters to
    them is that whatever is handed in reaches the page, not what it says.
    """
    return ViewerAssets(script="window.BpmnJS = function () {};", styles=".djs-container { outline: none; }")


@pytest.fixture
def enrollment_skeleton() -> Skeleton:
    """The real enrollment skeleton, loaded from disk."""
    return load_skeleton(ENROLLMENT_DIR / "skeleton.json")


@pytest.fixture
def enrollment_config() -> ProcessConfig:
    """The real enrollment metadata, loaded from disk."""
    return load_process_config(ENROLLMENT_DIR)


@pytest.fixture
def valid_graph() -> ProcessGraph:
    """A structurally sound graph.

    Exercises every modelling decision the validator depends on: a single start
    collapsing multiple intake channels, subprocesses as single collapsed boxes,
    a gateway with two conditioned branches, and an annotation hanging off a task
    by a dashed edge. It deliberately omits the two missing-info subprocesses so
    the resolution tier has something to report.
    """
    nodes = (
        node("start_intake", NodeType.START, subprocess="intake", detail="via the portal or manually via fax"),
        node("transcribe_pef", subprocess="intake", actor="CM360"),
        node("off_label_review", NodeType.SUBPROCESS, subprocess="off_label"),
        node("gw_patient_exists", NodeType.GATEWAY, subprocess="duplicate"),
        node("create_patient_record", subprocess="duplicate", actor="CM360"),
        node("onboarding", NodeType.SUBPROCESS, subprocess="onboarding"),
        node("end_enrolled", NodeType.TERMINAL),
        node("end_existing_patient", NodeType.TERMINAL, subprocess="duplicate"),
        node("ann_bi_status", NodeType.ANNOTATION, label="status = PENDING, substatus = NEW PATIENT - HUB ENROLLED"),
    )
    edges = (
        edge("start_intake", "transcribe_pef"),
        edge("transcribe_pef", "off_label_review"),
        edge("off_label_review", "gw_patient_exists"),
        branch("gw_patient_exists", "create_patient_record", "patient is new", order=0),
        branch("gw_patient_exists", "end_existing_patient", "patient already exists", order=1),
        edge("create_patient_record", "onboarding"),
        edge("onboarding", "end_enrolled"),
        edge("ann_bi_status", "create_patient_record", EdgeType.ANNOTATES),
    )
    return graph(nodes, edges)
