"""Per-process settings, read from ``processes/<name>/metadata.yaml``.

Adding a process means copying a folder and swapping the data. Nothing in this
module knows anything about enrollment specifically.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

METADATA_FILENAME = "metadata.yaml"
SKELETON_FILENAME = "skeleton.json"
INPUTS_DIRNAME = "inputs"
OUTPUTS_DIRNAME = "outputs"


class ProcessConfig(BaseModel):
    """Settings for one business process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_name: str = Field(min_length=1, description="Machine name; matches the folder under processes/.")
    display_name: str = Field(min_length=1, description="Human-readable name for prompts and reports.")
    actors: tuple[str, ...] = Field(
        default=(),
        description="Actor vocabulary for this process, e.g. HCP, CM360, PSM, QRAL.",
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Domain shorthand the source text uses without expanding, mapped to its meaning.",
    )
    model_id: str | None = Field(
        default=None,
        description="Optional per-process model override. None uses the global default.",
    )


def load_process_config(process_dir: Path) -> ProcessConfig:
    """Read a process's ``metadata.yaml``.

    Args:
        process_dir: The ``processes/<name>/`` directory.

    Returns:
        The parsed process config.

    Raises:
        FileNotFoundError: If ``metadata.yaml`` does not exist.
        pydantic.ValidationError: If the file does not match the schema.
    """
    raw: Any = yaml.safe_load((process_dir / METADATA_FILENAME).read_text(encoding="utf-8"))
    return ProcessConfig.model_validate(raw)
