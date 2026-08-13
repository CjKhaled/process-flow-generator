"""The extraction loop.

One structured-output call, gated by the deterministic validator, retried a
bounded number of times when the result is mechanically defective.

The distinction the loop turns on:

* A **mechanical** defect -- the response did not fit the schema, or the graph
  fails a structural rule -- is something the model can see and fix. It earns a
  retry with the specific complaint fed back.
* **Ambiguity** in the source is not a defect. It is the output of this stage.
  Resolution findings never trigger a retry; retrying them would only pressure
  the model into inventing content the source does not support.

This module imports no SDK. The model is injected as a :class:`ModelCall`, which
is what lets the loop be tested without a network.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

from extractors.errors import ExtractionError, SchemaCallError
from extractors.prompt import build_extraction_prompt, build_repair_prompt
from ir.models import ProcessGraph
from ir.skeleton import Skeleton
from validators.graph import validate
from validators.report import ValidationReport

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
"""Fallback for direct callers only. A pipeline run passes the configured budget in."""


class ModelCall(Protocol):
    """Sends one turn and returns the graph the model produced.

    Implementations are expected to be stateful across calls, so a repair turn
    continues the same conversation and the model can see its own previous answer.
    """

    def __call__(self, prompt: str) -> ProcessGraph:
        """Send ``prompt`` and return the parsed graph.

        Raises:
            SchemaCallError: If the response did not fit the schema.
        """
        ...


@dataclass(frozen=True)
class ExtractionResult:
    """A graph that passed the structural tier, with the findings that came with it."""

    graph: ProcessGraph
    report: ValidationReport
    attempts: int


def extract(
    source_text: str,
    skeleton: Skeleton,
    *,
    call: ModelCall,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ExtractionResult:
    """Extract a validated process graph from source text.

    Args:
        source_text: The written process description.
        skeleton: The subprocesses this process is expected to contain.
        call: The model. Injected so the loop can be tested without a network.
        max_attempts: How many times to ask, including the first attempt.

    Returns:
        The graph and its validation report. The graph is guaranteed to pass the
        structural tier; the report may still carry resolution findings.

    Raises:
        ValueError: If ``max_attempts`` is not positive.
        ExtractionError: If no attempt produced a structurally valid graph.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    prompt = build_extraction_prompt(source_text)
    last_report: ValidationReport | None = None
    last_schema_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            graph = call(prompt)
        except SchemaCallError as error:
            last_report, last_schema_error = None, str(error)
            logger.warning("attempt %d/%d: response did not fit the schema: %s", attempt, max_attempts, error)
            prompt = build_repair_prompt(None, schema_error=str(error))
            continue

        report = validate(graph, skeleton)
        if report.is_structurally_valid:
            logger.info("attempt %d/%d: accepted", attempt, max_attempts)
            return ExtractionResult(graph=graph, report=report, attempts=attempt)

        last_report, last_schema_error = report, None
        logger.warning(
            "attempt %d/%d: %d structural defect(s):\n%s",
            attempt,
            max_attempts,
            len(report.structural),
            "\n".join(f"  - {f.code}: {f.message}" for f in report.structural),
        )
        prompt = build_repair_prompt(report)

    raise ExtractionError(
        f"no structurally valid graph after {max_attempts} attempt(s)",
        attempts=max_attempts,
        report=last_report,
        schema_error=last_schema_error,
    )
