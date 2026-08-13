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


class ModelUnavailableError(Exception):
    """The API rejected the request outright -- bad model id, bad key, quota.

    Deliberately not a :class:`SchemaCallError`: the retry loop must not re-prompt
    its way through an authentication failure or a typo in a model id.
    """


class ExtractionError(Exception):
    """Extraction did not yield a structurally valid graph within the attempt budget."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        report: ValidationReport | None,
        schema_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.report = report
        """The last validation report, or None if the final attempt never parsed."""
        self.schema_error = schema_error
        """The final attempt's schema complaint, if that is how it failed."""

    def reason(self) -> str:
        """Why the last attempt failed, whichever way it failed."""
        if self.schema_error is not None:
            return self.schema_error
        if self.report is not None:
            return self.report.summary()
        return "no diagnosis was recorded"
