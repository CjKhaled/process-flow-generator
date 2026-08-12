"""Shared fixtures."""

from pathlib import Path

import pytest

from ir.models import EdgeType, NodeType, ProcessGraph
from ir.skeleton import Skeleton, load_skeleton
from tests.builders import branch, edge, graph, node

REPO_ROOT = Path(__file__).resolve().parent.parent
ENROLLMENT_DIR = REPO_ROOT / "processes" / "enrollment"


@pytest.fixture
def enrollment_skeleton() -> Skeleton:
    """The real enrollment skeleton, loaded from disk."""
    return load_skeleton(ENROLLMENT_DIR / "skeleton.json")


@pytest.fixture
def valid_graph() -> ProcessGraph:
    """A structurally sound graph.

    Exercises every modelling decision the validator depends on: a single start
    collapsing multiple intake channels, subprocesses as single collapsed boxes,
    a gateway with two conditioned branches, an annotation hanging off a task by a
    dashed edge, and off_label running before duplicate (against the order hints).
    It deliberately omits the ``missing_info`` subprocess so the resolution tier
    has something to report.
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
