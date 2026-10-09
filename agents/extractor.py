"""The patch extractor: new statements in, graph changes out. Nothing else.

The only agent that writes the graph, and the one kept furthest from the
knowledge base. Its system prompt is built from the patch rules, the extraction
conventions in :mod:`extractors.prompt`, and the session's vocabulary. It is never shown a knowledge file or the checklist.

The loop:

* one structured call, gated by the deterministic validators;
* a **structural** defect -- from the patch itself, from ``validate``, or from
  ``validate_session`` -- is fed back in the same conversation and earns a retry;
* a **resolution** finding never does. An open question is this stage's output,
  and "fixing" one would mean inventing what the user did not say.

Running out of attempts is an outcome, not an error. A conversation always has
the previous turn's graph, which is valid, so the graph is kept as it was and the
caller is told the statements still need applying.

The conversation is held across repair attempts within a turn and never across
turns. Each repair is a whole corrected patch against the *original* graph, not a
patch on top of the last attempt -- a rejected patch was never applied, so there
is nothing for a correction to build on.
"""

import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agents.prompts import load_prompt
from extractors.conversation import EXTRACTOR, ConversationFactory
from extractors.errors import SchemaCallError
from extractors.prompt import CONVENTIONS
from ir.models import ProcessGraph
from ir.skeleton import Skeleton, SubprocessSpec
from knowledge.compose import extractor_context
from knowledge.loader import DomainKnowledge
from session.models import Session, StatementOrigin, StepTiming
from session.patch import GraphPatch, apply_patch
from utils.logs import trace_context
from validators.graph import validate
from validators.report import Finding, FindingCode, ValidationReport
from validators.session_checks import check_removal_reasons, validate_session

logger = logging.getLogger(__name__)

STEP = "extractor"

DEFAULT_MAX_ATTEMPTS = 3
"""The attempt budget when no settings are in hand: a caller that injected its own model."""

_SESSION_NOISE = frozenset({FindingCode.MISSING_REQUIRED_SUBPROCESS})
"""Resolution findings ``validate`` raises that mean nothing mid-conversation.

A subprocess nobody has described yet is not an open question about the graph;
it is a topic the conversation has not reached, and the ledger already tracks it.
"""


@dataclass(frozen=True)
class Correction:
    """Something the user took back or contradicted, for the extractor to act on."""

    statement_ids: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class ExtractionOutcome:
    """What one turn's extraction did."""

    graph: ProcessGraph
    """The new graph, or the previous one when no attempt was accepted."""
    updated: bool
    patch: GraphPatch | None
    attempts: int
    structural: tuple[Finding, ...]
    """Empty when the graph was updated; the last attempt's defects when it was not."""
    resolution: tuple[Finding, ...]
    timings: tuple[StepTiming, ...]


def session_skeleton(session: Session, domain: DomainKnowledge) -> Skeleton:
    """The process's subprocesses, as the skeleton ``validate`` expects.

    The lane is the session's default: mid-conversation only the names matter,
    and the lane each box is finally drawn in is worked out at close-out.
    """
    return Skeleton(
        subprocesses=tuple(
            SubprocessSpec(name=sub.id, label=sub.label, actor=session.default_lane)
            for sub in domain.process.subprocesses
        )
    )


def check(graph: ProcessGraph, session: Session, domain: DomainKnowledge) -> ValidationReport:
    """Both validators over one graph, as one report.

    Used for every attempt, and by anything else that needs to know whether a
    session's graph is fit to show.
    """
    base = validate(graph, session_skeleton(session, domain))
    conversational = validate_session(graph, session.corpus, session.lanes, domain.process)
    findings = [finding for finding in base.findings if finding.code not in _SESSION_NOISE]
    return ValidationReport(findings=(*findings, *conversational.findings))


def extract_patch(
    session: Session,
    domain: DomainKnowledge,
    new_statement_ids: Sequence[str],
    corrections: Sequence[Correction] = (),
    *,
    conversations: ConversationFactory,
    max_attempts: int,
    clock: Callable[[], float] = time.perf_counter,
) -> ExtractionOutcome:
    """Bring the session's graph up to date with this turn's statements.

    Args:
        session: The session, with this turn's statements already in its corpus
            and its lanes already updated. Not modified.
        domain: The knowledge base. Read for vocabulary only.
        new_statement_ids: This turn's statements.
        corrections: What the user took back this turn.
        conversations: Where the model comes from.
        max_attempts: How many times to ask, including the first attempt.
        clock: A monotonic clock, injected so timings can be tested.

    Returns:
        The outcome. ``updated`` is False when no attempt produced a
        structurally valid graph, in which case ``graph`` is the session's own.

    Raises:
        ValueError: If ``max_attempts`` is not positive.
        extractors.errors.ModelUnavailableError: If the API rejected the request.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    conversation = conversations.open(EXTRACTOR, build_system_prompt(session, domain))
    prompt = build_prompt(session, new_statement_ids, corrections)
    timings: list[StepTiming] = []
    structural: tuple[Finding, ...] = ()

    for attempt in range(1, max_attempts + 1):
        started = clock()
        try:
            with trace_context(attempt=attempt):
                patch = conversation.send(prompt, GraphPatch)
        except SchemaCallError as error:
            timings.append(StepTiming(step=STEP, attempt=attempt, seconds=clock() - started))
            logger.warning("attempt %d/%d: the patch did not fit the schema: %s", attempt, max_attempts, error)
            structural = ()
            prompt = build_repair_prompt((), schema_error=str(error))
            continue
        timings.append(StepTiming(step=STEP, attempt=attempt, seconds=clock() - started))

        logger.info(
            "attempt %d/%d: patch of %d operation(s): %s",
            attempt,
            max_attempts,
            len(patch.operations),
            ", ".join(f"{count} {name}" for name, count in Counter(op.op for op in patch.operations).items()) or "none",
        )
        graph, patch_findings = apply_patch(session.graph, patch)
        report = check(graph, session, domain)
        structural = (*patch_findings, *check_removal_reasons(patch, session.corpus), *report.structural)
        if not structural:
            logger.info("attempt %d/%d: accepted, %d operation(s)", attempt, max_attempts, len(patch.operations))
            return ExtractionOutcome(
                graph=graph,
                updated=True,
                patch=patch,
                attempts=attempt,
                structural=(),
                resolution=report.resolution,
                timings=tuple(timings),
            )

        logger.warning(
            "attempt %d/%d: %d structural defect(s):\n%s",
            attempt,
            max_attempts,
            len(structural),
            "\n".join(f"  - {finding.code}: {finding.message}" for finding in structural),
        )
        prompt = build_repair_prompt(structural)

    return ExtractionOutcome(
        graph=session.graph,
        updated=False,
        patch=None,
        attempts=max_attempts,
        structural=structural,
        resolution=check(session.graph, session, domain).resolution,
        timings=tuple(timings),
    )


def build_system_prompt(session: Session, domain: DomainKnowledge) -> str:
    """The extractor's instructions: patch rules, the shared conventions, this session's vocabulary."""
    return "\n\n".join(
        [
            load_prompt("extractor_patch", domain.process.display_name),
            "In the conventions below, 'the source' means the user's numbered statements.",
            CONVENTIONS,
            extractor_context(domain, session),
        ]
    )


def build_prompt(session: Session, new_statement_ids: Sequence[str], corrections: Sequence[Correction] = ()) -> str:
    """The opening turn: the graph as it stands, every statement, and what is new."""
    new = set(new_statement_ids)
    retry = set(session.retry_statement_ids)
    lines = []
    for statement in session.corpus:
        marker = "NEW" if statement.id in new else "RETRY" if statement.id in retry else "applied"
        origin = (
            "description"
            if statement.origin is StatementOrigin.INITIAL_DESCRIPTION
            else f"answer, turn {statement.turn}"
        )
        lines.append(f"{statement.id} [{marker}; {origin}] {statement.raw_text}")
        if statement.restatement:
            lines.append(f"    restatement: {statement.restatement}")

    graph = json.dumps(session.graph.model_dump(mode="json", exclude_defaults=True), ensure_ascii=False)
    sections = [
        "Update the process graph for the statements marked NEW or RETRY.",
        f"<graph>\n{graph}\n</graph>" if session.graph.nodes else "<graph>\nEmpty. This is the first turn.\n</graph>",
        "<statements>\n" + "\n".join(lines) + "\n</statements>",
    ]
    if corrections:
        listed = "\n".join(
            f"- ({', '.join(correction.statement_ids) or 'no statement'}) {correction.description}"
            for correction in corrections
        )
        sections.append(
            "<corrections>\nThe user has corrected earlier content. Change or remove what these "
            f"contradict, citing the statements given.\n{listed}\n</corrections>"
        )
    return "\n\n".join(sections)


def build_repair_prompt(structural: Sequence[Finding], *, schema_error: str | None = None) -> str:
    """A repair turn naming the specific defects.

    Only structural defects are ever named. Resolution findings are the correct
    output of the stage, and asking the model to "fix" one would invite it to
    invent what the user did not say.
    """
    if schema_error is not None:
        return (
            "That response did not fit the schema. The validator reported:\n\n"
            f"{schema_error}\n\n"
            "Return the whole patch again, correcting that. Do not change its content beyond what "
            "the error requires."
        )
    listed = "\n".join(f"- {finding.code}: {finding.message}" for finding in structural)
    return (
        "Applied to the graph you were given, that patch does not leave a structurally valid graph. "
        "These defects must be fixed:\n\n"
        f"{listed}\n\n"
        "Return the whole corrected patch, against the same original graph -- your previous patch "
        "was not applied. Fix only these defects; keep every other node and edge as it was. Where "
        "a defect exists because the user never stated an outcome, close it with a terminal marked "
        "`status: needs_clarification` and `origin: rule` rather than inventing what happens. Where "
        "a quote was not found, copy it exactly from the statement, or cite the statement that "
        "actually supports the node."
    )
