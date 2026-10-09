"""What each agent is told about the domain. Pure string building, no I/O.

This module is where the project's hardest rule is enforced: **domain knowledge
drives questions, never content.** Three agents, three very different views:

* The **navigator** reads everything -- every markdown file and the whole
  checklist -- because knowing how these programs usually run is what lets it ask
  a useful question. It cannot edit the graph.
* The **extractor** reads none of it. It gets the session's lanes, the glossary
  and the subprocess names, which is vocabulary: enough to put a step in the
  right lane and to read an acronym, and nothing that says what a program
  *usually* does. A step in the graph that came from the knowledge base rather
  than from the user would look exactly like a real one.
* The **interpreter** sits between: topic ids, titles and cues, so it can say
  which topics a message addressed, but not the questions or the prose.

``tests/test_knowledge_compose.py`` asserts the extractor's view contains no
checklist text and no markdown, so the rule cannot erode by accident.
"""

from knowledge.loader import DomainKnowledge
from knowledge.schemas import Topic, TopicStatus
from session.models import LaneStatus, Session

_OPEN_STATUSES = frozenset(
    {
        TopicStatus.NOT_YET_COVERED,
        TopicStatus.ASKED,
        TopicStatus.NEEDS_CLARIFICATION,
        TopicStatus.DEFERRED,
    }
)


def navigator_knowledge(domain: DomainKnowledge) -> str:
    """Everything the navigator knows about the domain, as one block.

    Depends on the knowledge base alone -- nothing from a session -- so it is the
    same text on every turn of every session about this process, which is what
    lets it be cached.

    Args:
        domain: The loaded knowledge base.

    Returns:
        The process definition, every markdown file in full under a header naming
        its path, then the whole checklist.
    """
    process = domain.process
    sections = [
        f"# Process: {process.display_name}\n\n{process.description}\n\n"
        f"Starts at: {process.scope.starts_at}\n\n"
        "In scope:\n" + "\n".join(f"- {item}" for item in process.scope.in_scope) + "\n\n"
        "Out of scope:\n" + "\n".join(f"- {item}" for item in process.scope.out_of_scope),
        "# Subprocesses\n\n"
        + "\n".join(
            f"- `{sub.id}` -- {sub.label}. Entered when: {sub.entry}. "
            f"Outcomes: {'; '.join(exit_.label for exit_ in sub.exits)}."
            for sub in process.subprocesses
        ),
        "# Process boundaries\n\n"
        + "\n".join(
            f"- `{boundary.id}` -- {boundary.label}." + (f" {boundary.note}" if boundary.note else "")
            for boundary in process.boundaries
        ),
    ]
    sections.extend(f"# Knowledge file: {document.path}\n\n{document.body}" for document in domain.documents)
    sections.append(
        "# Coverage checklist\n\n" + "\n\n".join(_checklist_entry(topic) for topic in domain.checklist.topics)
    )
    return "\n\n".join(sections)


def _checklist_entry(topic: Topic) -> str:
    lines = [
        f"## {topic.id} -- {topic.title}",
        f"scope: {topic.scope} | priority: {topic.priority}" + (" | screening" if topic.screening else ""),
        f"ask: {topic.ask}",
    ]
    if topic.follow_ups:
        lines.append("follow-ups: " + " / ".join(topic.follow_ups))
    if topic.leads_to:
        lines.append("hands off to: " + ", ".join(topic.leads_to))
    return "\n".join(lines)


def extractor_context(domain: DomainKnowledge, session: Session) -> str:
    """The vocabulary the extractor may use, and nothing else from the knowledge base.

    Args:
        domain: The loaded knowledge base. Read for persona lane descriptions,
            the glossary and the subprocess names only.
        session: Supplies the lanes and terms this conversation has learned.

    Returns:
        Three sections: swimlanes with the default lane named, subprocess
        values, and shorthand.
    """
    lanes = "\n".join(f"- **{lane.name}** -- {lane_description(domain, session, lane.name)}" for lane in session.lanes)
    subprocesses = "\n".join(f"- `{sub.id}` -- {sub.label}" for sub in domain.process.subprocesses)
    return "\n\n".join(
        [
            "## Swimlanes\n\n"
            "These are the lanes learned so far. Use these names verbatim, exactly as written "
            "here, wherever one of them is who a statement means. What each one is matters: it is "
            "how you tell which lane a box belongs in. If a statement attributes work to someone "
            "not listed, use the statement's own name for them.\n\n"
            f"{lanes}\n\n"
            "Where the statements do not say who performs a step, it is automatic: use "
            f"`{session.default_lane}`.",
            "## Known subprocesses\n\n"
            "These are the only values the `subprocess` field may take. Leave it null for a node "
            "that sits outside all of them. If the statements do not describe one, leave it "
            "absent from the graph. Do not invent steps to fill it in.\n\n"
            f"{subprocesses}",
            "## Domain shorthand\n\n"
            "The statements use these without expanding them. They are not actors.\n\n" + _glossary(domain, session),
        ]
    )


def lane_description(domain: DomainKnowledge, session: Session, name: str) -> str:
    """What a lane is: its persona's description, then whatever the user said about it.

    Shared with close-out, which writes the same sentence into ``metadata.yaml``,
    so the extractor and the final diagram's config describe a lane identically.
    """
    lane = session.lane(name)
    if lane is None:
        return ""
    persona = domain.personas.get(lane.persona) if lane.persona else None
    parts = [persona.lane_description if persona else "", lane.description]
    if lane.status is LaneStatus.PLACEHOLDER:
        parts.append("A placeholder until the user names the system that does automated work.")
    return " ".join(part.strip() for part in parts if part.strip()) or "A lane the user named."


def interpreter_context(domain: DomainKnowledge, session: Session) -> str:
    """What the interpreter needs to place a message: topics, vocabulary, lanes, facts.

    Args:
        domain: The loaded knowledge base.
        session: Supplies which topics are still open and which facts are unknown.

    Returns:
        Open and pending topics as id, title and cues -- not their questions --
        with the glossary, the persona list, the subprocesses and the program
        facts still unknown.
    """
    pending = {topic_id for question in session.pending for topic_id in question.topic_ids}
    status_of = {entry.topic_id: entry.status for entry in session.ledger}
    topics = "\n".join(
        f"- `{topic.id}` [{topic.scope}] {topic.title} -- cues: {', '.join(topic.cues) or 'none'}"
        for topic in domain.checklist.topics
        if topic.id in pending or status_of.get(topic.id, TopicStatus.NOT_YET_COVERED) in _OPEN_STATUSES
    )
    personas = "\n".join(
        f"- `{persona_id}` -- {persona.name}. {persona.lane_description} "
        f"Often called: {', '.join(persona.common_titles) or 'n/a'}."
        for persona_id, persona in domain.personas.items()
    )
    subprocesses = "\n".join(
        f"- `{sub.id}` -- {sub.label}. Entered when: {sub.entry}" for sub in domain.process.subprocesses
    )
    unknown_facts = "\n".join(
        f"- `{fact.value}` -- settled by topic `{topic.id}` ({topic.title})"
        for topic in domain.checklist.topics
        if (fact := topic.sets_fact) is not None and session.facts.get(fact) is None
    )
    return "\n\n".join(
        [
            "## Coverage topics still open\n\nIds, titles and cue words. The cues are hints, not keyword rules.\n\n"
            + (topics or "None."),
            "## Subprocesses\n\n" + subprocesses,
            "## Personas\n\nThe only values a lane's `persona` may take.\n\n" + personas,
            "## Program facts not yet known\n\n" + (unknown_facts or "None."),
            "## Glossary\n\nKnown shorthand. None of these is a lane.\n\n" + _glossary(domain, session),
        ]
    )


def _glossary(domain: DomainKnowledge, session: Session) -> str:
    """The domain glossary with this session's learned terms, sorted, learned terms winning."""
    terms = {
        term: entry.meaning + (f" (also: {', '.join(entry.aliases)})" if entry.aliases else "")
        for term, entry in domain.glossary.items()
    }
    terms.update({learned.term: learned.meaning for learned in session.glossary})
    return "\n".join(
        f"- **{term}**: {meaning}" for term, meaning in sorted(terms.items(), key=lambda pair: pair[0].lower())
    )
