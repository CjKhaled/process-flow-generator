"""Global settings, read from the environment.

Loaded through :func:`load_settings` rather than instantiated at import time.
A module-level singleton would make importing anything in this package fail when
``ANTHROPIC_API_KEY`` is unset -- which is exactly the situation the test suite
runs in, since no test touches the network.

Stage 2 has its own settings class rather than sharing :class:`Settings`. It
calls no model and needs no credentials, so requiring an API key to draw a
diagram from a graph already on disk would be a startup failure for no reason.
:class:`SessionSettings` is separate for the same reason: where the knowledge base
and the session files live is needed to load a session, list one or serve one,
none of which calls a model.
"""

from pathlib import Path

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


    interpreter_model_id: str | None = Field(
        default=None,
        alias="PFG_INTERPRETER_MODEL_ID",
        description=(
            "Model the conversation's interpreter runs on. None uses PFG_MODEL_ID. The "
            "interpreter only reads one message against what was asked, so it is the role "
            "that can run on a faster, cheaper model."
        ),
    )
    extractor_model_id: str | None = Field(
        default=None,
        alias="PFG_EXTRACTOR_MODEL_ID",
        description="Model the conversation's patch extractor runs on. None uses PFG_MODEL_ID.",
    )
    navigator_model_id: str | None = Field(
        default=None,
        alias="PFG_NAVIGATOR_MODEL_ID",
        description="Model the conversation's navigator runs on. None uses PFG_MODEL_ID.",
    )

    def model_for(self, role: str) -> str:
        """The model id one conversational role runs on.

        Args:
            role: ``interpreter``, ``extractor`` or ``navigator``.

        Returns:
            That role's override, or the global model id where it has none --
            including for a role this class has never heard of, so a new agent
            works before anyone has thought to give it a setting.
        """
        override: str | None = getattr(self, f"{role}_model_id", None)
        return override or self.model_id


class SessionSettings(BaseSettings):
    """Where a conversation's knowledge is read from and its state is kept.

    Every field has a default, and no credential is among them: a session is
    loaded, listed and served far more often than it calls a model.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    domain_dir: Path = Field(
        default=Path("domain_knowledge"),
        alias="PFG_DOMAIN_DIR",
        description="The knowledge base. A relative path is taken from the repository root.",
    )
    sessions_dir: Path = Field(
        default=Path("sessions"),
        alias="PFG_SESSIONS_DIR",
        description=(
            "Where sessions are written, one folder each. A relative path is taken from "
            "the repository root. Gitignored: a session holds what somebody typed."
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


class ApiSettings(BaseSettings):
    """Settings for the hosted demo's HTTP service. Every field has a default.

    The service needs an ``ANTHROPIC_API_KEY`` to run a pipeline, but not to
    start: :class:`Settings` is loaded when a run begins, so a misconfigured
    instance answers ``/health`` and says what is wrong on the first run rather
    than crash-looping at boot.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    allowed_origins: str = Field(
        default="*",
        alias="PFG_ALLOWED_ORIGIN",
        description=(
            "Comma-separated origins the browser page may call from, e.g. "
            "'https://user.github.io'. The default allows any, which is right only "
            "while the URL is unpublished."
        ),
    )
    max_source_chars: int = Field(
        default=20_000,
        gt=0,
        alias="PFG_MAX_SOURCE_CHARS",
        description=(
            "Longest process description accepted. Not a security control -- it is "
            "the difference between a paste that costs a few cents and one that "
            "costs a great deal more."
        ),
    )

    @property
    def origins(self) -> list[str]:
        """The origin list, as CORS wants it."""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


def load_api_settings() -> ApiSettings:
    """Read the HTTP service's settings from the environment.

    Returns:
        The validated settings. Never raises for a missing value.
    """
    return ApiSettings()


REPO_ROOT = Path(__file__).resolve().parent.parent


def load_session_settings() -> SessionSettings:
    """Read the conversation's directories from the environment.

    Returns:
        The settings, with both directories made absolute. Never raises for a
        missing value.
    """
    settings = SessionSettings()
    return settings.model_copy(
        update={
            "domain_dir": _from_root(settings.domain_dir),
            "sessions_dir": _from_root(settings.sessions_dir),
        }
    )


def _from_root(path: Path) -> Path:
    """A relative path, read from the repository root rather than from wherever the process started."""
    return path if path.is_absolute() else REPO_ROOT / path


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
