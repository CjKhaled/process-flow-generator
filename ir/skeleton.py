"""The expected-subprocess list for a process.

A skeleton says which named subprocesses a complete extraction *should* contain.
It drives two things:

* the "is a part missing?" check in the resolution tier of the validator -- a
  required subprocess with no node claiming it becomes a finding rather than
  disappearing silently;
* the collapse in stage 2 -- every subprocess listed here is drawn as one box,
  with its steps left out of the diagram.

Because of the second, this list is not a coverage checklist for the whole
process. It names the stretches of work the source *hands off* at a decision, and
those alone. The steps of the running narrative belong to no subprocess and are
drawn one by one, so listing them here would make them vanish.

``actor`` is the lane the collapsed box is drawn in, and is declared rather than
inferred: the lane that owns a subprocess is frequently not the lane that
performs most of its steps, so there is no rule to derive it from.

There is no ordering field. Declaration order here is presentation order -- it is
the sequence the subprocesses are listed in for the prompt and reported in by the
validator, and nothing more. It must never be enforced, because real source text
routinely runs the subprocesses out of any expected order, and it does not place
anything either: stage 2 draws each box where the first of its steps appeared.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SubprocessSpec(BaseModel):
    """One subprocess a complete extraction is expected to contain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Machine name, matched against Node.subprocess.")
    label: str = Field(min_length=1, description="Human-readable name for prompts and reports.")
    actor: str = Field(
        min_length=1, description="The swimlane the collapsed box is drawn in. Must be a declared actor."
    )


class Skeleton(BaseModel):
    """The set of subprocesses a process is expected to contain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subprocesses: tuple[SubprocessSpec, ...] = Field(min_length=1)

    @property
    def required_names(self) -> frozenset[str]:
        """The subprocess names every complete extraction should account for."""
        return frozenset(spec.name for spec in self.subprocesses)


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
