"""The knowledge base, checked as it is committed.

The schemas in :mod:`knowledge.schemas` hold each record's shape. What is checked
here is what the files must agree on *between themselves* -- the things a domain
expert editing one file can break in another without any single record being
wrong. Every test reads the real ``domain_knowledge/``: these are properties of
that data, so a stand-in would prove nothing.
"""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from knowledge.loader import DomainKnowledge, list_domain_processes, load_domain
from knowledge.schemas import MAIN_SCOPE, BoundaryKind, ExitKind, ProgramFact
from tests.conftest import DOMAIN_DIR, DOMAIN_PROCESS

_MARKDOWN_REFERENCE = re.compile(r"`([^`\s]+\.md)`")


def test_every_file_loads_through_its_schema(domain: DomainKnowledge) -> None:
    assert domain.process.id == DOMAIN_PROCESS
    assert domain.checklist.process == DOMAIN_PROCESS
    assert domain.personas and domain.glossary and domain.documents


def test_markdown_is_loaded_agnostic_first_then_by_path(domain: DomainKnowledge) -> None:
    """The order is what makes the navigator's knowledge block the same text every turn."""
    paths = [document.path for document in domain.documents]
    agnostic = [path for path in paths if path.startswith("agnostic/")]

    assert paths == sorted(agnostic) + sorted(path for path in paths if path not in agnostic)


def test_every_markdown_file_has_an_id_and_a_title(domain: DomainKnowledge) -> None:
    for document in domain.documents:
        assert document.front.id == Path(document.path).stem
        assert document.front.title
        assert document.body


def test_the_process_is_offered(domain: DomainKnowledge) -> None:
    assert (DOMAIN_PROCESS, domain.process.display_name) in list_domain_processes(DOMAIN_DIR)


def test_an_unknown_process_is_a_missing_file_not_a_crash() -> None:
    with pytest.raises(FileNotFoundError, match="no_such_process"):
        load_domain("no_such_process", DOMAIN_DIR)


def test_topic_ids_are_unique(domain: DomainKnowledge) -> None:
    counts = Counter(topic.id for topic in domain.checklist.topics)

    assert [topic_id for topic_id, count in counts.items() if count > 1] == []


def test_every_topic_sits_in_a_declared_scope(domain: DomainKnowledge) -> None:
    scopes = set(domain.process.scopes)

    assert [topic.id for topic in domain.checklist.topics if topic.scope not in scopes] == []


def test_a_subprocess_topic_is_prefixed_with_its_scope(domain: DomainKnowledge) -> None:
    """The prefix is how a reader, and the knowledge files, tell which flow a topic belongs to."""
    stray = [
        topic.id
        for topic in domain.checklist.topics
        if topic.scope != MAIN_SCOPE and not topic.id.startswith(f"{topic.scope}.")
    ]

    assert stray == []


def test_every_hand_off_names_a_real_subprocess(domain: DomainKnowledge) -> None:
    known = set(domain.process.subprocess_ids)
    dangling = [
        (topic.id, target) for topic in domain.checklist.topics for target in topic.leads_to if target not in known
    ]

    assert dangling == []


def test_every_subprocess_is_reached_by_some_topic(domain: DomainKnowledge) -> None:
    """A subprocess nothing hands off to could never become the conversation's focus."""
    reached = {target for topic in domain.checklist.topics for target in topic.leads_to}

    assert set(domain.process.subprocess_ids) - reached == set()


def test_each_program_fact_has_exactly_one_screening_topic(domain: DomainKnowledge) -> None:
    """Two would ask the same thing twice; none would leave the fact unknowable."""
    setters = Counter(topic.sets_fact for topic in domain.checklist.topics if topic.sets_fact is not None)

    assert setters == dict.fromkeys(ProgramFact, 1)


def test_a_topic_that_sets_a_fact_is_a_screening_topic(domain: DomainKnowledge) -> None:
    for topic in domain.checklist.topics:
        assert topic.screening == (topic.sets_fact is not None), topic.id


def test_conditions_use_only_the_program_facts(domain: DomainKnowledge) -> None:
    """Enforced by the schema's enum; asserted so the four facts are named somewhere a reader will look."""
    used = {fact for topic in domain.checklist.topics if topic.applies_when != "always" for fact in topic.applies_when}
    used |= {fact for persona in domain.personas.values() if persona.applies_when for fact in persona.applies_when}

    assert used <= set(ProgramFact)
    assert used, "no topic is conditional, so the screening topics would do nothing"


def test_every_persona_referenced_exists(domain: DomainKnowledge) -> None:
    known = set(domain.personas)
    referenced = {domain.process.default_persona, *domain.process.typical_personas}
    referenced |= {sub.persona for sub in domain.process.subprocesses}
    referenced |= {other for persona in domain.personas.values() for other in persona.overlaps_with}

    assert referenced - known == set()


def test_the_process_ends_only_at_declared_boundaries(domain: DomainKnowledge) -> None:
    boundaries = {boundary.id for boundary in domain.process.boundaries}
    exits = {exit_.id for sub in domain.process.subprocesses for exit_ in sub.exits if exit_.kind is ExitKind.BOUNDARY}

    assert set(domain.process.scope.ends_at) - boundaries == set()
    assert exits - boundaries == set()


def test_a_hand_off_boundary_is_one_the_process_can_end_at(domain: DomainKnowledge) -> None:
    ends = set(domain.process.scope.ends_at)

    assert {b.id for b in domain.process.boundaries if b.kind is BoundaryKind.HANDOFF} <= ends


def test_every_subprocess_knowledge_file_exists(domain: DomainKnowledge) -> None:
    loaded = {document.path for document in domain.documents}

    for sub in domain.process.subprocesses:
        assert f"{DOMAIN_PROCESS}/{sub.knowledge}" in loaded, sub.id


def test_no_glossary_term_is_also_a_persona_title(domain: DomainKnowledge) -> None:
    """A role must never be mistaken for a term, or a term for a role."""
    titles = {
        title.casefold() for persona in domain.personas.values() for title in (persona.name, *persona.common_titles)
    }
    terms = {name.casefold() for term, entry in domain.glossary.items() for name in (term, *entry.aliases)}

    assert terms & titles == set()


def test_every_markdown_path_mentioned_in_a_body_resolves(domain: DomainKnowledge) -> None:
    """Paths are relative to the file that mentions them, as a reader would follow them."""
    broken = []
    for document in domain.documents:
        folder = (DOMAIN_DIR / document.path).parent
        for mentioned in _MARKDOWN_REFERENCE.findall(document.body):
            if not (folder / mentioned).resolve().is_file():
                broken.append((document.path, mentioned))

    assert broken == []


def test_an_unknown_fact_never_switches_a_topic_off(domain: DomainKnowledge) -> None:
    topic = domain.topic("nurse.offer")
    assert topic is not None

    assert topic.applies(dict.fromkeys(ProgramFact))
    assert topic.applies({ProgramFact.HAS_NURSE_PROGRAM: True})
    assert not topic.applies({ProgramFact.HAS_NURSE_PROGRAM: False})


def test_an_empty_markdown_file_is_skipped_and_a_headerless_one_is_refused(tmp_path: Path) -> None:
    """A placeholder says nothing; a file with text and no header was started and not finished."""
    root = tmp_path / "knowledge"
    shutil.copytree(DOMAIN_DIR, root)
    (root / "agnostic" / "placeholder.md").write_text("", encoding="utf-8")

    assert "agnostic/placeholder.md" not in {d.path for d in load_domain(DOMAIN_PROCESS, root).documents}

    other = tmp_path / "other"
    shutil.copytree(DOMAIN_DIR, other)
    (other / "agnostic" / "notes.md").write_text("# Notes\n\nNo header.", encoding="utf-8")
    with pytest.raises(ValueError, match="front matter"):
        load_domain(DOMAIN_PROCESS, other)
