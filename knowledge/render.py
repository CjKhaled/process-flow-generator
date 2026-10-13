"""The knowledge base as something a person can read.

Everything the conversation knows about a process, turned into plain pages: the
markdown files rendered as prose, and the YAML files -- the process definition,
the coverage checklist, the personas, the glossary -- written out as sentences
and lists, not shown as code. It is what the page's "View knowledge" opens, so a
subject-matter expert can see what the tool will ask about and why, and say when
it is wrong.

Pure, like :mod:`knowledge.compose`: a function of the loaded knowledge base and
nothing else. And like the questions panel of stage 3's page, the HTML is built
here and not in the browser, so what the page says and how it is escaped have one
home. Every value that comes from a YAML file is escaped; the markdown files are
the project's own and are rendered as written.

This is the **whole** knowledge base, with nothing held back. That is deliberate
and it is safe: the rule about who reads what (:mod:`knowledge.compose`) is about
which *agent* sees which file, so that nothing about other programs reaches the
graph. A person reading it changes nothing a session draws.
"""

from dataclasses import dataclass
from html import escape

import markdown

from knowledge.loader import DomainKnowledge, KnowledgeDocument
from knowledge.schemas import MAIN_SCOPE, ExitKind, Topic

PROCESS_GROUP = "This process"
SHARED_GROUP = "Shared across processes"

_MARKDOWN_EXTENSIONS = ("tables", "sane_lists")

_PRIORITY_WORDS = {"high": "High priority", "normal": "Normal priority", "low": "Low priority"}

_FACT_WORDS = {
    "product.has_rems": "a product has a REMS",
    "program.has_nurse_program": "the program has nurse or educator support",
    "program.patient_self_enrollment": "patients can start an enrollment themselves",
    "product.pediatric_population": "the program enrolls patients under 18",
}
"""Each program fact as the end of a sentence beginning "Only asked when ..."."""


@dataclass(frozen=True)
class KnowledgeSection:
    """One page of the knowledge view."""

    id: str
    group: str
    title: str
    html: str


def knowledge_sections(domain: DomainKnowledge) -> tuple[KnowledgeSection, ...]:
    """Every part of the knowledge base, as readable pages, in reading order.

    Args:
        domain: The loaded knowledge base for one process.

    Returns:
        The process's own pages first -- what it is, what a complete description
        covers, then its topic files -- followed by what every process shares:
        roles, shorthand and background.
    """
    process_dir = f"{domain.process.id}/"
    own = [document for document in domain.documents if document.path.startswith(process_dir)]
    shared = [document for document in domain.documents if not document.path.startswith(process_dir)]
    return (
        KnowledgeSection("process", PROCESS_GROUP, "The process", _process(domain)),
        KnowledgeSection("checklist", PROCESS_GROUP, "What gets asked", _checklist(domain)),
        *(_document(document, PROCESS_GROUP) for document in own),
        KnowledgeSection("personas", SHARED_GROUP, "Roles and lanes", _personas(domain)),
        KnowledgeSection("glossary", SHARED_GROUP, "Glossary", _glossary(domain)),
        *(_document(document, SHARED_GROUP) for document in shared),
    )


def _document(document: KnowledgeDocument, group: str) -> KnowledgeSection:
    """One markdown file, rendered. Its own first heading is its title, so it is not repeated."""
    html = markdown.markdown(document.body, extensions=list(_MARKDOWN_EXTENSIONS))
    return KnowledgeSection(
        id=document.path.removesuffix(".md").replace("/", "-"),
        group=group,
        title=document.front.title,
        html=html,
    )


def _items(values: tuple[str, ...] | list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(value)}</li>" for value in values) + "</ul>"


def _process(domain: DomainKnowledge) -> str:
    """The process definition: what it covers, where it ends, and the subprocesses it hands off to."""
    process = domain.process
    boundaries = {boundary.id: boundary for boundary in process.boundaries}
    ends = "".join(
        f"<li><strong>{escape(boundaries[end].label)}</strong>"
        + (f"<br>{escape(boundaries[end].note or '')}" if boundaries[end].note else "")
        + "</li>"
        for end in process.scope.ends_at
        if end in boundaries
    )
    subprocesses = "".join(
        f"<h3>{escape(sub.label)}</h3>"
        f"<p><strong>Entered when:</strong> {escape(sub.entry)}</p>"
        "<p><strong>Ways out:</strong></p><ul>"
        + "".join(
            f"<li>{escape(exit_.label)} "
            f"<em>({'back to the main flow' if exit_.kind is ExitKind.RETURN else 'ends the process'})</em></li>"
            for exit_ in sub.exits
        )
        + "</ul>"
        for sub in process.subprocesses
    )
    return (
        f"<h1>{escape(process.display_name)}</h1>"
        f"<p>{escape(process.description)}</p>"
        f"<h2>Where it starts</h2><p>{escape(process.scope.starts_at)}</p>"
        f"<h2>Where it ends</h2><ul>{ends}</ul>"
        f"<h2>In scope</h2>{_items(process.scope.in_scope)}"
        f"<h2>Out of scope</h2>{_items(process.scope.out_of_scope)}"
        "<h2>Subprocesses</h2>"
        "<p>Stretches of work the main flow hands off. Each is drawn as one box on the main flow "
        "and can be opened as a flow of its own.</p>"
        f"{subprocesses}"
    )


def _checklist(domain: DomainKnowledge) -> str:
    """The coverage topics, grouped by flow: what a complete description would settle."""
    process = domain.process
    parts = [
        "<h1>What gets asked</h1>",
        "<p>The topics a complete description of this process would settle. They decide what the "
        "conversation asks about, in roughly this order within each flow. They never decide what "
        "is drawn: a step appears only when you describe it.</p>",
    ]
    for scope in process.scopes:
        topics = [topic for topic in domain.checklist.topics if topic.scope == scope]
        if not topics:
            continue
        label = "Main flow" if scope == MAIN_SCOPE else process.scope_label(scope)
        parts.append(f"<h2>{escape(label)}</h2>")
        parts.extend(_topic(topic, domain) for topic in topics)
    return "".join(parts)


def _topic(topic: Topic, domain: DomainKnowledge) -> str:
    notes = [_PRIORITY_WORDS[topic.priority.value]]
    if topic.screening:
        notes.append("asked early: the answer decides whether other topics apply")
    if topic.applies_when != "always":
        conditions = " and ".join(
            _FACT_WORDS[fact.value] if wanted else f"it is not the case that {_FACT_WORDS[fact.value]}"
            for fact, wanted in topic.applies_when.items()
        )
        notes.append(f"only asked when {conditions}")
    if topic.leads_to:
        notes.append("hands off to " + ", ".join(domain.process.scope_label(target) for target in topic.leads_to))
    follow_ups = "<p><strong>If the answer is thin:</strong></p>" + _items(topic.follow_ups) if topic.follow_ups else ""
    return (
        f'<div class="topic"><h3>{escape(topic.title)}</h3>'
        f'<p class="note">{escape("; ".join(notes))}</p>'
        f"<p>{escape(topic.ask)}</p>{follow_ups}</div>"
    )


def _personas(domain: DomainKnowledge) -> str:
    """The kinds of role a lane can be. Responsibilities, not job titles."""
    parts = [
        "<h1>Roles and lanes</h1>",
        "<p>The kinds of role a swimlane can be. These are responsibilities, not job titles: a "
        "session learns its own lane names from what you say, and matches each to one of these.</p>",
    ]
    for persona in domain.personas.values():
        parts.append(f"<h2>{escape(persona.name)}</h2><p>{escape(persona.lane_description)}</p>")
        if persona.responsibilities:
            parts.append("<p><strong>Typically:</strong></p>" + _items(persona.responsibilities))
        if persona.common_titles:
            parts.append(f"<p><strong>Often called:</strong> {escape(', '.join(persona.common_titles))}</p>")
    return "".join(parts)


def _glossary(domain: DomainKnowledge) -> str:
    """Domain shorthand, grouped by what kind of thing each term names."""
    by_category: dict[str, list[str]] = {}
    for term, entry in domain.glossary.items():
        aliases = f" <em>(also: {escape(', '.join(entry.aliases))})</em>" if entry.aliases else ""
        by_category.setdefault(entry.category.value, []).append(
            f"<dt>{escape(term)}</dt><dd>{escape(entry.meaning)}{aliases}</dd>"
        )
    parts = [
        "<h1>Glossary</h1>",
        "<p>Shorthand the tool already understands. None of these is a role: role titles are "
        "under Roles and lanes.</p>",
    ]
    for category, entries in by_category.items():
        parts.append(f"<h2>{escape(category.capitalize())}</h2><dl>{''.join(entries)}</dl>")
    return "".join(parts)
