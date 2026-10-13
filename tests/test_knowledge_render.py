"""The knowledge base as pages a person can read."""

import re

from knowledge.loader import DomainKnowledge
from knowledge.render import PROCESS_GROUP, SHARED_GROUP, knowledge_sections


def html_of(domain: DomainKnowledge, section_id: str) -> str:
    return next(section.html for section in knowledge_sections(domain) if section.id == section_id)


def test_every_part_of_the_knowledge_base_has_a_page(domain: DomainKnowledge) -> None:
    """Nothing is held back: a person reading it is how it gets corrected."""
    sections = knowledge_sections(domain)
    titles = {section.title for section in sections}

    assert {"The process", "What gets asked", "Roles and lanes", "Glossary"} <= titles
    assert {document.front.title for document in domain.documents} <= titles
    assert len(sections) == 4 + len(domain.documents)
    assert len({section.id for section in sections}) == len(sections)


def test_the_processs_own_pages_come_before_what_is_shared(domain: DomainKnowledge) -> None:
    groups = [section.group for section in knowledge_sections(domain)]

    assert groups == sorted(groups, key=[PROCESS_GROUP, SHARED_GROUP].index)
    assert html_of(domain, "enrollment_and_intake-channels")
    assert next(s.group for s in knowledge_sections(domain) if s.id == "agnostic-consent") == SHARED_GROUP


def test_markdown_is_rendered_as_prose_not_shown_as_source(domain: DomainKnowledge) -> None:
    for document in domain.documents:
        html = html_of(domain, document.path.removesuffix(".md").replace("/", "-"))

        assert "<h1>" in html and "<p>" in html, document.path
        assert not re.search(r"^#{1,6} ", html, re.MULTILINE), f"{document.path}: a heading was left as markup"
        assert "\n---" not in html and "id:" not in html.split("<h1>")[0], f"{document.path}: front matter leaked"


def test_a_markdown_table_becomes_a_table(domain: DomainKnowledge) -> None:
    html = html_of(domain, "agnostic-hub_vendors")

    assert "<table>" in html and "<th>" in html
    assert "| Model |" not in html


def test_the_process_page_says_what_it_covers_and_where_it_ends(domain: DomainKnowledge) -> None:
    html = html_of(domain, "process")

    assert "<h1>Intake &amp; Enrollment</h1>" in html
    assert "Handed off to benefits investigation" in html and "Closed, not enrolled" in html
    assert "Buy-and-bill products" in html
    for sub in domain.process.subprocesses:
        assert f"<h3>{sub.label}</h3>" in html
    assert "back to the main flow" in html and "ends the process" in html


def test_the_checklist_page_gives_every_topic_its_question_in_words(domain: DomainKnowledge) -> None:
    html = html_of(domain, "checklist")

    assert html.count('<div class="topic">') == len(domain.checklist.topics)
    assert "How do enrollment submissions arrive today?" in html
    assert "<h2>Main flow</h2>" in html and "<h2>Off-label review</h2>" in html
    assert "only asked when the program has nurse or educator support" in html
    assert "hands off to Off-label review" in html
    assert "High priority" in html and "Low priority" in html


def test_no_page_shows_yaml_or_internal_ids_where_words_belong(domain: DomainKnowledge) -> None:
    """Rendered as text a person reads, not as the files they came from."""
    for section_id in ("process", "checklist", "personas", "glossary"):
        html = html_of(domain, section_id)

        assert "applies_when" not in html and "schema_version" not in html, section_id
        assert "program.has_nurse_program" not in html and "hub_case_owner" not in html, section_id
        assert "intake.channels" not in html, section_id


def test_roles_are_described_by_what_they_do_and_what_they_are_called(domain: DomainKnowledge) -> None:
    html = html_of(domain, "personas")

    assert "<h2>Case owner</h2>" in html
    assert "Owns missing information and consent outreach" in html
    assert "Often called:" in html and "patient access manager" in html


def test_the_glossary_is_grouped_and_lists_other_names(domain: DomainKnowledge) -> None:
    html = html_of(domain, "glossary")

    assert "<h2>Consent</h2>" in html and "<h2>Platform</h2>" in html
    assert "<dt>PEF</dt>" in html
    assert "also: enrollment form" in html


def test_text_from_the_files_is_escaped(domain: DomainKnowledge) -> None:
    """The ampersand in the process's own name is the case that is always there."""
    assert "Intake & Enrollment" not in html_of(domain, "process")
    assert "<script" not in "".join(section.html for section in knowledge_sections(domain))
