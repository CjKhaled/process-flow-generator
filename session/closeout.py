"""Close-out: one session in, a finished diagram per flow out.

The conversation ends by handing each flow -- the main flow, and every
subprocess that has steps -- to stages 2 and 3, **unchanged**. This module does
not draw anything. It composes what those stages already read and calls what they
already call:

* per flow, a folder in the layout ``processes/<name>/`` has always had:
  ``metadata.yaml``, ``skeleton.json``, ``outputs/graph.json`` and
  ``outputs/validation.json``;
* then the same in-memory functions ``pipelines/stage2.py`` and
  ``pipelines/stage3.py`` compose -- translate, render, lay out, widen, colour,
  build the page.

There is no second copy of a stage here and there must never be one. A folder
written by close-out can be re-run with ``pipelines.stage2 --processes-root`` and
produce the same diagram, which is the check that this stayed true.

What a session knows that a hand-written ``metadata.yaml`` had to be told is
worked out here: the actors are the lanes the flow actually uses, described the
way the extractor was told about them; the skeleton lists the subprocesses that
actually have steps, each in the lane of whoever hands off to it.

:func:`compose_flow` is pure, so what gets written can be tested without writing
it. :func:`finalise` is the only function that touches the disk or the layouter.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from bpmn import colors, decisions, document, semantics
from bpmn.autolayout import Layouter, subprocess_layouter
from ir.models import ProcessGraph
from ir.process_config import (
    GRAPH_FILENAME,
    METADATA_FILENAME,
    OUTPUTS_DIRNAME,
    REPORT_FILENAME,
    SKELETON_FILENAME,
    ProcessConfig,
)
from ir.skeleton import Skeleton, SubprocessSpec
from knowledge.compose import lane_description
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE
from render import page
from render.assets import ViewerAssets, load_assets, load_template
from session.ledger import ledger_findings, open_items
from session.models import Phase, Session, TurnStatus
from session.slicing import flow_name, handoff_lane, members, slice_subprocess
from session.store import SessionStore
from utils.io import write_json
from utils.settings import load_stage2_settings
from validators.graph import validate
from validators.report import ValidationReport

logger = logging.getLogger(__name__)

DIAGRAM_FILENAME = "diagram.bpmn"
PAGE_FILENAME = "diagram.html"

DOWNLOADS = (DIAGRAM_FILENAME, PAGE_FILENAME, GRAPH_FILENAME)
"""The files a finished flow offers for download, in the order they are listed."""


class NothingToDraw(ValueError):
    """The session has no flow to finish: nothing was ever extracted."""


@dataclass(frozen=True)
class FlowBundle:
    """Everything stages 2 and 3 need for one flow."""

    scope: str
    """``main``, or the subprocess id. Also the folder the flow is written to."""
    config: ProcessConfig
    skeleton: Skeleton
    graph: ProcessGraph
    report: ValidationReport


def flow_scopes(session: Session, domain: DomainKnowledge) -> tuple[str, ...]:
    """The flows this session has: the main flow, then each subprocess with at least one step."""
    return (
        MAIN_SCOPE,
        *(sub.id for sub in domain.process.subprocesses if members(session.graph, sub.id)),
    )


def compose_flow(session: Session, domain: DomainKnowledge, scope: str) -> FlowBundle:
    """Build one flow's config, skeleton, graph and report from the session.

    Args:
        session: The session, with its master graph frozen.
        domain: The knowledge base.
        scope: ``main``, or a subprocess id that has steps.

    Returns:
        The bundle. Pure: nothing is written.

    Raises:
        NothingToDraw: If the scope has no steps.
    """
    process = domain.process
    if scope == MAIN_SCOPE:
        if not session.graph.nodes:
            raise NothingToDraw("the session has no flow yet")
        graph = session.graph
        skeleton = Skeleton(
            subprocesses=tuple(
                SubprocessSpec(name=sub.id, label=sub.label, actor=handoff_lane(session, process, sub))
                for sub in process.subprocesses
                if members(session.graph, sub.id)
            )
        )
        name, display_name = flow_name(process), process.display_name
    else:
        sub = process.subprocess(scope)
        sliced = slice_subprocess(session.graph, sub, process) if sub is not None else None
        if sub is None or sliced is None:
            raise NothingToDraw(f"the '{scope}' flow has no steps")
        graph, skeleton = sliced, Skeleton(subprocesses=())
        name, display_name = flow_name(process, scope), f"{process.display_name}: {sub.label}"

    used = [node.actor for node in graph.nodes if node.actor] + [spec.actor for spec in skeleton.subprocesses]
    config = ProcessConfig(
        process_name=name,
        display_name=display_name,
        actors={lane: lane_description(domain, session, lane) for lane in _lane_order(session, domain, used)},
        default_actor=session.default_lane,
        glossary=_glossary(session, domain),
    )

    present = {node.id for node in graph.nodes}
    ledger = tuple(
        finding.model_copy(update={"node_ids": tuple(n for n in finding.node_ids if n in present)})
        for finding in ledger_findings(session.ledger, domain, scope)
    )
    report = validate(graph, skeleton)
    return FlowBundle(
        scope=scope,
        config=config,
        skeleton=skeleton,
        graph=graph,
        report=ValidationReport(findings=(*report.findings, *ledger)),
    )


def _lane_order(session: Session, domain: DomainKnowledge, used: list[str]) -> list[str]:
    """The flow's lanes, top to bottom.

    By the process's usual order of personas first, so a diagram reads the way
    these flows conventionally do -- the office at the top, the system at the
    bottom -- and by first appearance among lanes that order says nothing about.
    The default lane is always included, used or not: ``ProcessConfig`` requires
    the default to be a declared actor, and stage 2 draws no lane for an actor
    nothing sits in.
    """
    typical = {persona: index for index, persona in enumerate(domain.process.typical_personas)}
    names = list(dict.fromkeys([*used, session.default_lane]))

    def position(name: str) -> tuple[int, int]:
        lane = session.lane(name)
        persona = lane.persona if lane else None
        return (typical.get(persona or "", len(typical)), names.index(name))

    return sorted(names, key=position)


def _glossary(session: Session, domain: DomainKnowledge) -> dict[str, str]:
    """The domain's shorthand with the session's learned terms, which win on a clash."""
    return {
        **{term: entry.meaning for term, entry in domain.glossary.items()},
        **{learned.term: learned.meaning for learned in session.glossary},
    }


def write_flow(folder: Path, bundle: FlowBundle) -> None:
    """Write one flow's folder, in the layout stages 2 and 3 read.

    Args:
        folder: The flow's folder. Created as needed.
        bundle: What to write.
    """
    folder.mkdir(parents=True, exist_ok=True)
    (folder / METADATA_FILENAME).write_text(
        yaml.safe_dump(bundle.config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    write_json(folder / SKELETON_FILENAME, bundle.skeleton)
    write_json(folder / OUTPUTS_DIRNAME / GRAPH_FILENAME, bundle.graph)
    write_json(folder / OUTPUTS_DIRNAME / REPORT_FILENAME, bundle.report)


def draw(bundle: FlowBundle, layout: Layouter) -> str:
    """Stage 2 for one flow: the same five calls ``pipelines/stage2.py`` makes.

    Raises:
        ValueError: If a node names a lane the config does not declare.
        bpmn.autolayout.LayoutError: If the diagram could not be laid out.
    """
    definitions = semantics.translate(bundle.graph, bundle.config, bundle.skeleton)
    return colors.apply(decisions.widen(layout(document.render(definitions))))


def finalise(
    session: Session,
    domain: DomainKnowledge,
    store: SessionStore,
    *,
    layout: Layouter | None = None,
    assets: ViewerAssets | None = None,
) -> Session:
    """Accept what is still open, and produce the final BPMN and HTML for every flow.

    Args:
        session: The session to finish. Never modified.
        domain: The knowledge base.
        store: Says where each flow's folder goes.
        layout: The layouter. Defaults to the pinned CLI; injecting one lets this
            be exercised without Node.
        assets: The viewer's files. Defaults to the vendored install and the
            built bundle; injecting stubs lets this be exercised without either.

    Returns:
        The session, complete, with every open item recorded as accepted.

    Raises:
        NothingToDraw: If the session has no flow.
        session.slicing.SliceError: If a subprocess could not be sliced.
        bpmn.autolayout.LayoutError: If a diagram could not be laid out.
        render.assets.AssetError: If the viewer's files are not installed.
        ValueError: If a node names a lane the session does not have.
    """
    working = session.model_copy(deep=True)
    working.accepted_open_items = list(
        dict.fromkeys([*working.accepted_open_items, *(item.key for item in open_items(working, domain))])
    )

    if layout is None:
        layout_bin = load_stage2_settings().layout_bin
        layout = subprocess_layouter([layout_bin] if layout_bin else None)
    viewer = assets or load_assets()
    template = load_template()

    # Everything is composed and drawn before anything is written, so a flow that
    # cannot be drawn leaves no half-finished set of folders behind.
    drawn = []
    scopes = flow_scopes(working, domain)
    logger.info(
        "finalising session %s: %d flow(s) (%s); %d open item(s) accepted as open",
        working.id,
        len(scopes),
        ", ".join(scopes),
        len(working.accepted_open_items),
    )
    for scope in scopes:
        bundle = compose_flow(working, domain, scope)
        logger.info(
            "flow '%s': %d nodes, %d edges, lanes %s, %d box(es), %d finding(s)",
            scope,
            len(bundle.graph.nodes),
            len(bundle.graph.edges),
            ", ".join(bundle.config.actors),
            len(bundle.skeleton.subprocesses),
            len(bundle.report.findings),
        )
        diagram = draw(bundle, layout)
        html = page.build(
            diagram,
            bundle.report.resolution,
            bundle.config.display_name,
            viewer,
            template,
            semantics.element_ids(bundle.graph, bundle.skeleton),
        )
        drawn.append((bundle, diagram, html))

    for bundle, diagram, html in drawn:
        folder = store.path_for_outputs(working.id, bundle.scope)
        write_flow(folder, bundle)
        (folder / OUTPUTS_DIRNAME / DIAGRAM_FILENAME).write_text(diagram, encoding="utf-8")
        (folder / OUTPUTS_DIRNAME / PAGE_FILENAME).write_text(html, encoding="utf-8")
        logger.info("flow '%s' written to %s", bundle.scope, folder)

    working.phase = Phase.COMPLETE
    working.pending = []
    working.turn_status = TurnStatus.IDLE
    working.turn_error = None
    return working


def list_outputs(session: Session, domain: DomainKnowledge, store: SessionStore) -> list[dict[str, object]]:
    """The finished flows and the files each offers, for the download list.

    Returns:
        One entry per flow that has been written, in flow order: its scope, its
        label, and the names of the files present.
    """
    listed: list[dict[str, object]] = []
    for scope in flow_scopes(session, domain):
        outputs = store.path_for_outputs(session.id, scope) / OUTPUTS_DIRNAME
        files = [name for name in DOWNLOADS if (outputs / name).is_file()]
        if files:
            listed.append({"flow": scope, "label": domain.process.scope_label(scope), "files": files})
    return listed
