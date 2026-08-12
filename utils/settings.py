"""Global settings, read from the environment.

Loaded through :func:`load_settings` rather than instantiated at import time.
A module-level singleton would make importing anything in this package fail when
``ANTHROPIC_API_KEY`` is unset -- which is exactly the situation the test suite
runs in, since no test touches the network.
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
        default="claude-opus-5",
        alias="PFG_MODEL_ID",
        description="Model used for extraction unless a process overrides it.",
    )
    max_tokens: int = Field(
        default=32000,
        gt=0,
        alias="PFG_MAX_TOKENS",
        description="Output cap per call. The provider streams, so a generous value is safe.",
    )
    max_extraction_attempts: int = Field(
        default=3,
        ge=1,
        alias="PFG_MAX_EXTRACTION_ATTEMPTS",
        description="How many times to ask the model, including the first attempt.",
    )


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
