"""Prompt construction tests. No network."""

from extractors.prompt import build_extraction_prompt, build_repair_prompt, build_system_prompt
from ir.process_config import ProcessConfig
from ir.skeleton import Skeleton
from validators.report import Finding, FindingCode, ValidationReport


def config(**overrides: object) -> ProcessConfig:
    defaults: dict[str, object] = {
        "process_name": "enrollment",
        "display_name": "Patient Enrollment",
        "actors": {
            "HCP": "the provider who gives the patient the prescription",
            "CM360": "an external hub that performs some enrollment activities",
            "JCRM": "the Salesforce platform, which runs automations",
        },
        "default_actor": "JCRM",
        "glossary": {"PEF": "Patient Enrollment Form"},
    }
    return ProcessConfig.model_validate(defaults | overrides)


def test_system_prompt_lists_the_known_subprocesses(enrollment_skeleton: Skeleton) -> None:
    """The extractor can only tag a subprocess it has been told about."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    for name in enrollment_skeleton.required_names:
        assert name in prompt
    assert "Off-Label Review" in prompt


def test_system_prompt_lists_actors_and_glossary(enrollment_skeleton: Skeleton) -> None:
    """Domain vocabulary is supplied so the model does not paraphrase or guess."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    assert "CM360" in prompt
    assert "Patient Enrollment Form" in prompt


def test_system_prompt_explains_what_each_actor_is(enrollment_skeleton: Skeleton) -> None:
    """A bare name cannot tell the model which actor an unattributed step belongs to."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    assert "the Salesforce platform, which runs automations" in prompt


def test_system_prompt_keeps_the_configured_actor_order(enrollment_skeleton: Skeleton) -> None:
    """Actors read in process order; sorting them would scramble that."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    assert prompt.index("**HCP**") < prompt.index("**CM360**") < prompt.index("**JCRM**")


def test_system_prompt_names_the_default_lane(enrollment_skeleton: Skeleton) -> None:
    """An unattributed step goes somewhere specific, not to null."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    assert "does not say who performs a step" in prompt
    assert "`JCRM`" in prompt


def test_system_prompt_falls_back_to_null_without_a_default_lane(enrollment_skeleton: Skeleton) -> None:
    """A process that declares no default lane must not be told to invent one."""
    prompt = build_system_prompt(config(default_actor=None), enrollment_skeleton)

    assert "leave `actor` null" in prompt


def test_system_prompt_encodes_the_extraction_conventions(enrollment_skeleton: Skeleton) -> None:
    """These conventions are what make the emitted graph born valid."""
    prompt = build_system_prompt(config(), enrollment_skeleton).lower()

    assert "exactly one" in prompt and "start" in prompt
    assert "needs_clarification" in prompt
    assert "annotation" in prompt
    assert "alternatives" in prompt
    assert "stated" in prompt
    assert "inferred" not in prompt, "there is no middle status; offering one invites gap-filling"


def test_system_prompt_does_not_name_the_subprocess_order(enrollment_skeleton: Skeleton) -> None:
    """order_hint is a layout hint; telling the model about it would bias extraction."""
    prompt = build_system_prompt(config(), enrollment_skeleton)

    assert "order_hint" not in prompt


def test_extraction_prompt_embeds_the_source_text() -> None:
    """The source text is the only thing the first turn adds."""
    prompt = build_extraction_prompt("HCP can complete the PEF online via the portal.")

    assert "HCP can complete the PEF online via the portal." in prompt


def test_repair_prompt_names_the_structural_defects() -> None:
    """The retry turn feeds back the specific defect, not a generic 'try again'."""
    report = ValidationReport(
        findings=(
            Finding.of(FindingCode.GATEWAY_BRANCHES, "gateway 'gw_agrees' has 1 branch edge(s)", "gw_agrees"),
            Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "the source does not describe 'missing_info'"),
        )
    )

    prompt = build_repair_prompt(report)

    assert "gw_agrees" in prompt
    assert FindingCode.GATEWAY_BRANCHES in prompt


def test_repair_prompt_omits_resolution_findings() -> None:
    """Ambiguity is not a defect to fix; asking the model to 'fix' it invites invention."""
    report = ValidationReport(
        findings=(
            Finding.of(FindingCode.GATEWAY_BRANCHES, "gateway 'gw' has 1 branch edge(s)", "gw"),
            Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "the source does not describe 'missing_info'"),
            Finding.of(FindingCode.NEEDS_CLARIFICATION, "node 'end_unknown' needs confirmation", "end_unknown"),
        )
    )

    prompt = build_repair_prompt(report)

    assert "missing_info" not in prompt
    assert "end_unknown" not in prompt


def test_repair_prompt_for_a_schema_failure() -> None:
    """A mechanical schema failure has no report, only the message from the SDK."""
    prompt = build_repair_prompt(None, schema_error="alternatives: Input should be a valid list")

    assert "alternatives: Input should be a valid list" in prompt
