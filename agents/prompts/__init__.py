"""The agents' system prompts, as markdown files beside this module.

Kept as files rather than as strings in code so the wording can be edited, read
and reviewed without touching Python. Each takes one substitution, the process's
display name, made with plain ``str.replace`` -- the prompts are full of braces
and backticks, which rules out ``str.format``.
"""

from functools import cache
from pathlib import Path

_DISPLAY_NAME = "{display_name}"


@cache
def _read(name: str) -> str:
    return (Path(__file__).resolve().parent / f"{name}.md").read_text(encoding="utf-8").strip()


def load_prompt(name: str, display_name: str) -> str:
    """Read one prompt and name the process in it.

    Args:
        name: The file's stem: ``interpreter``, ``extractor_patch`` or ``navigator``.
        display_name: The process's human-readable name.

    Returns:
        The prompt text.

    Raises:
        FileNotFoundError: If there is no such prompt. They ship with the
            project, so this is a broken checkout.
    """
    return _read(name).replace(_DISPLAY_NAME, display_name)
