"""Close-out against the real layouter and the real viewer bundle.

The one place the conversation's output meets the pinned ``bpmn-auto-layout`` and
our own built script, so it is the regression guard for the claim that a flow
sliced from a session is a process stages 2 and 3 can draw. Skipped without Node,
an install and the build.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bpmn.decisions import BPMNDI_NS
from bpmn.document import BPMN_NS
from knowledge.loader import DomainKnowledge
from session.closeout import finalise, flow_scopes
from session.store import FileSessionStore
from tests.conftest import requires_bundle
from tests.master_graph import master_session

pytestmark = requires_bundle

FLOW_ELEMENTS = ("startEvent", "endEvent", "task", "exclusiveGateway", "subProcess")


@pytest.fixture(scope="module")
def flows(tmp_path_factory: pytest.TempPathFactory, domain: DomainKnowledge) -> dict[str, Path]:
    """Every flow of the four-subprocess session, finished once for the module."""
    store = FileSessionStore(tmp_path_factory.mktemp("sessions"))
    session = finalise(master_session(domain), domain, store)
    return {scope: store.path_for_outputs(session.id, scope) / "outputs" for scope in flow_scopes(session, domain)}


def test_every_flow_is_laid_out_with_a_shape_for_each_element(flows: dict[str, Path]) -> None:
    assert len(flows) == 5
    for scope, outputs in flows.items():
        diagram = ET.fromstring((outputs / "diagram.bpmn").read_text(encoding="utf-8"))
        elements = {e.get("id", "") for kind in FLOW_ELEMENTS for e in diagram.iter(f"{{{BPMN_NS}}}{kind}")}
        shaped = {shape.get("bpmnElement", "") for shape in diagram.iter(f"{{{BPMNDI_NS}}}BPMNShape")}

        assert elements, scope
        assert elements <= shaped, f"{scope}: {sorted(elements - shaped)} were not drawn"


def test_every_flow_has_a_lane_for_each_actor_it_draws(flows: dict[str, Path]) -> None:
    for scope, outputs in flows.items():
        diagram = ET.fromstring((outputs / "diagram.bpmn").read_text(encoding="utf-8"))

        assert list(diagram.iter(f"{{{BPMN_NS}}}lane")), scope


def test_every_flow_gets_a_self_contained_page(flows: dict[str, Path]) -> None:
    for scope, outputs in flows.items():
        html = (outputs / "diagram.html").read_text(encoding="utf-8")

        assert "PFG" in html and "bpmn:definitions" in html, scope
        assert len(html) > 100_000, f"{scope}: the viewer bundle was not inlined"
