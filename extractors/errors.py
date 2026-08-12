"""Extraction failures.

Kept free of any Strands import so the retry loop can be exercised without the
SDK. The Strands adapter in :mod:`extractors.model` translates SDK exceptions
into :class:`SchemaCallError`.
"""

from validators.report import ValidationReport


class SchemaCallError(Exception):
    """The model produced something that does not fit the schema.

    A mechanical defect: the model can see the complaint and fix it, so the loop
    retries. Distinct from ambiguity in the source, which is never retried.
    """


class ExtractionError(Exception):
    """Extraction did not yield a structurally valid graph within the attempt budget."""

    def __init__(self, message: str, *, attempts: int, report: ValidationReport | None) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.report = report
        """The last validation report, or None if no attempt ever parsed."""
