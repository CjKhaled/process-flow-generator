"""Per-process settings, read from ``processes/<name>/metadata.yaml``.

Adding a process means copying a folder and swapping the data. Nothing in this
module knows anything about enrollment specifically.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

METADATA_FILENAME = "metadata.yaml"
SKELETON_FILENAME = "skeleton.json"
INPUTS_DIRNAME = "inputs"
OUTPUTS_DIRNAME = "outputs"


class ProcessConfig(BaseModel):
    """Settings for one business process. Takes in name, model, and glossary"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process_name: str = Field(min_length=1, description="Machine name; matches the folder under processes/.")
    display_name: str = Field(min_length=1, description="Human-readable name for prompts and reports.")
    actors: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Who performs work in this process, mapped to what each one is, e.g. "
            "{'CM360': 'an external hub that performs some enrollment activities'}. The "
            "descriptions are what let the extractor attribute a step to the right actor "
            "rather than leaving it blank. Declaration order is preserved into the prompt."
        ),
    )
    default_actor: str | None = Field(
        default=None,
        description=(
            "The lane a step falls to when the source does not say who performs it -- "
            "typically the system that runs the process's automations. Must be one of "
            "'actors'. None leaves unattributed steps blank."
        ),
    )
    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Domain shorthand the source text uses without expanding, mapped to its meaning.",
    )
    model_id: str | None = Field(
        default=None,
        description="Optional per-process model override. None uses the global default.",
    )

    @model_validator(mode="after")
    def _default_actor_is_known(self) -> "ProcessConfig":
        """A default lane naming an unlisted actor would put a stranger in every automated box."""
        if self.default_actor is not None and self.default_actor not in self.actors:
            known = ", ".join(self.actors) or "none are declared"
            raise ValueError(f"default_actor '{self.default_actor}' is not one of the actors ({known})")
        return self


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
    raw: Any = yaml.safe_load(
        (process_dir / METADATA_FILENAME).read_text(encoding="utf-8")
    )  # safe easy to identify failures
    return ProcessConfig.model_validate(raw)
