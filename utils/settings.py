"""Global settings, read from the environment.

Loaded through :func:`load_settings` rather than instantiated at import time.
A module-level singleton would make importing anything in this package fail when
``ANTHROPIC_API_KEY`` is unset -- which is exactly the situation the test suite
runs in, since no test touches the network.

Stage 2 has its own settings class rather than sharing :class:`Settings`. It
calls no model and needs no credentials, so requiring an API key to draw a
diagram from a graph already on disk would be a startup failure for no reason.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Credentials and model defaults for a pipeline run."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr = Field(
        alias="ANTHROPIC_API_KEY",
        description="Anthropic API key. Required; there is no default.",
    )
    model_id: str = Field(
        default="claude-opus-4-8",
        alias="PFG_MODEL_ID",
        description="Model used for extraction unless a process overrides it.",
    )
    max_tokens: int = Field(
        default=32000,
        gt=0,
        alias="PFG_MAX_TOKENS",
        description=(
            "Output cap per call. A cap, not a reservation -- you are billed for what is "
            "generated -- and the provider streams, so a generous value is safe. Too low "
            "truncates the graph mid-generation: 4096 is not enough for a real process."
        ),
    )
    max_extraction_attempts: int = Field(
        default=3,
        ge=1,
        alias="PFG_MAX_EXTRACTION_ATTEMPTS",
        description=(
            "How many times to ask the model, including the first attempt. The single source "
            "of truth for the budget: a pipeline run never falls back to another default."
        ),
    )


class Stage2Settings(BaseSettings):
    """Settings for the layout stage. Every field has a default, deliberately."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    layout_bin: str = Field(
        default="",
        alias="PFG_LAYOUT_BIN",
        description=(
            "The bpmn-auto-layout executable. Empty uses the version pinned in js/, "
            "which is what any normal run wants; overriding it is for pointing at a "
            "different build while checking whether a layouter release changed the output."
        ),
    )


def load_stage2_settings() -> Stage2Settings:
    """Read the layout stage's settings from the environment.

    Returns:
        The validated settings. Never raises for a missing value: stage 2 runs
        without any configuration at all.
    """
    return Stage2Settings()


def load_settings() -> Settings:
    """Read settings from the environment.

    Returns:
        The validated settings.

    Raises:
        pydantic.ValidationError: If a required setting is missing or malformed.
            Callers surface this as a startup failure rather than letting a
            missing key fail mid-run.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
