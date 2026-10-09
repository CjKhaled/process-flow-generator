"""Read ``domain_knowledge/`` from disk, once per process.

Everything a conversation knows about the domain arrives through
:func:`load_domain`. The knowledge base is read-only at run time: nothing a user
says is ever written back into it, and what a session learns -- a client's own
system names, its lanes -- lives in that session.

Markdown is loaded **agnostic first, then the process folder, sorted by path**.
The order is load-bearing rather than tidy: the navigator's knowledge block is
built from it and must come out byte-identical every turn, because it is the part
of the prompt that is cached.
"""

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from knowledge.schemas import (
    ChecklistFile,
    FrontMatter,
    GlossaryFile,
    GlossaryTerm,
    Persona,
    PersonasFile,
    ProcessFile,
    Topic,
)
from utils.settings import load_session_settings

logger = logging.getLogger(__name__)

AGNOSTIC_DIRNAME = "agnostic"
PERSONAS_FILENAME = "personas.yaml"
GLOSSARY_FILENAME = "glossary.yaml"
PROCESS_FILENAME = "process.yaml"
CHECKLIST_FILENAME = "checklist.yaml"

_FENCE = "---"


@dataclass(frozen=True)
class KnowledgeDocument:
    """One markdown file: where it sits, its header, and its text."""

    path: str
    """Relative to the knowledge base, with forward slashes, e.g. ``agnostic/consent.md``."""
    front: FrontMatter
    body: str


@dataclass(frozen=True)
class DomainKnowledge:
    """Everything the knowledge base says about one process."""

    process: ProcessFile
    checklist: ChecklistFile
    personas: dict[str, Persona]
    glossary: dict[str, GlossaryTerm]
    documents: tuple[KnowledgeDocument, ...]

    def topic(self, topic_id: str) -> Topic | None:
        """The topic with this id, or None."""
        return next((topic for topic in self.checklist.topics if topic.id == topic_id), None)


def load_domain(process_id: str, root: Path | None = None) -> DomainKnowledge:
    """Load the knowledge base for one process.

    Args:
        process_id: The folder name under the knowledge base, e.g.
            ``enrollment_and_intake``.
        root: The knowledge base. Defaults to ``PFG_DOMAIN_DIR``.

    Returns:
        The parsed files. Cached per process, so the same object comes back on
        every call and anything built from it is built once.

    Raises:
        FileNotFoundError: If the process has no folder, or a required file is
            missing from it.
        pydantic.ValidationError: If a file does not match its schema.
        ValueError: If a markdown file has no front matter.
    """
    return _load((root or load_session_settings().domain_dir).resolve(), process_id)


def list_domain_processes(root: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Every process a conversation can be held about.

    Args:
        root: The knowledge base. Defaults to ``PFG_DOMAIN_DIR``.

    Returns:
        ``(id, display_name)`` for each folder holding a readable
        ``process.yaml``, in folder order. One that does not load is logged and
        skipped, as :func:`ir.process_config.list_processes` does and for the
        same reason: a half-written folder should hide itself, not the others.
    """
    base = (root or load_session_settings().domain_dir).resolve()
    found = []
    for directory in sorted(path for path in base.glob("*") if path.is_dir()):
        if not (directory / PROCESS_FILENAME).is_file():
            continue
        try:
            domain = _load(base, directory.name)
        except (OSError, ValueError) as error:
            logger.warning("skipping knowledge for '%s': %s", directory.name, error)
            continue
        found.append((directory.name, domain.process.display_name))
    return tuple(found)


@cache
def _load(root: Path, process_id: str) -> DomainKnowledge:
    process_dir = root / process_id
    if not (process_dir / PROCESS_FILENAME).is_file():
        raise FileNotFoundError(f"there is no knowledge for a '{process_id}' process under {root}")

    agnostic = root / AGNOSTIC_DIRNAME
    documents = [*_documents(agnostic, root), *_documents(process_dir, root)]
    return DomainKnowledge(
        process=ProcessFile.model_validate(_yaml(process_dir / PROCESS_FILENAME)),
        checklist=ChecklistFile.model_validate(_yaml(process_dir / CHECKLIST_FILENAME)),
        personas=PersonasFile.model_validate(_yaml(agnostic / PERSONAS_FILENAME)).personas,
        glossary=GlossaryFile.model_validate(_yaml(agnostic / GLOSSARY_FILENAME)).terms,
        documents=tuple(documents),
    )


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _documents(directory: Path, root: Path) -> list[KnowledgeDocument]:
    """The markdown files of one folder, in filename order.

    An empty file is skipped rather than rejected. A placeholder somebody has
    not written yet says nothing, and refusing to start a conversation over it
    would be a failure with no content behind it.
    """
    found = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        if not text.strip():
            logger.warning("knowledge file %s is empty; skipped", relative)
            continue
        front, body = _split_front_matter(text, relative)
        found.append(KnowledgeDocument(path=relative, front=front, body=body))
    return found


def _split_front_matter(text: str, name: str) -> tuple[FrontMatter, str]:
    """Separate a file's YAML header from its body.

    Raises:
        ValueError: If the file does not open with a fenced header. Every
            knowledge file carries one, so its absence is a file somebody
            started without finishing.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError(f"knowledge file {name} has no front matter")
    try:
        close = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == _FENCE)
    except StopIteration:
        raise ValueError(f"knowledge file {name} opens a front matter block and never closes it") from None
    front = FrontMatter.model_validate(yaml.safe_load("\n".join(lines[1:close])))
    return front, "\n".join(lines[close + 1 :]).strip()
