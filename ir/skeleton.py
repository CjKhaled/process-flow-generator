"""The expected-subprocess list for a process.

A skeleton says which named subprocesses a complete extraction *should* contain.
It drives the "is a part missing?" check in the resolution tier of the validator:
a required subprocess with no node claiming it becomes a finding rather than
disappearing silently.

``order_hint`` is a hint for later layout only. The validator must never enforce
it -- real source text routinely runs the subprocesses out of the expected order.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SubprocessSpec(BaseModel):
    """One subprocess a complete extraction is expected to contain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Machine name, matched against Node.subprocess.")
    label: str = Field(min_length=1, description="Human-readable name for prompts and reports.")
    order_hint: int = Field(ge=0, description="Expected position. A hint for layout; never enforced.")


class Skeleton(BaseModel):
    """The set of subprocesses a process is expected to contain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_name: str = Field(min_length=1)
    subprocesses: tuple[SubprocessSpec, ...] = Field(min_length=1)

    @property
    def required_names(self) -> frozenset[str]:
        """The subprocess names every complete extraction should account for."""
        return frozenset(spec.name for spec in self.subprocesses)

    def in_hint_order(self) -> tuple[SubprocessSpec, ...]:
        """The subprocesses sorted by ``order_hint``, for display in prompts."""
        return tuple(sorted(self.subprocesses, key=lambda spec: spec.order_hint))


def load_skeleton(path: Path) -> Skeleton:
    """Read a ``skeleton.json`` file.

    Args:
        path: Path to the process's ``skeleton.json``.

    Returns:
        The parsed skeleton.

    Raises:
        FileNotFoundError: If the file does not exist.
        pydantic.ValidationError: If the file does not match the schema.
    """
    return Skeleton.model_validate(json.loads(path.read_text(encoding="utf-8")))
