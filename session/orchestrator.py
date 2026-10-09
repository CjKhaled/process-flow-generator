"""The turn pipeline: what happens between one message and the next reply.

Plain Python, deliberately. A session is a long, human-paced loop that stops for
a person between every turn, with state that has to be inspectable and
replayable. Inside one turn the work is fixed and sequential, so there is nothing
for an agent framework's control flow to decide: three narrow agents, each
answering in a schema, called in order by code that owns everything between
them::

    turn 1 only   split the description into statements        (code)
    1  interpret  what did the message address?                (agent)
    2  apply      statements, ledger, lanes, terms, facts,     (code)
                  focus
    3  extract    new statements -> patch -> validate ->       (agent + code)
                  repair
    4  record     link topics to steps, findings, version      (code)
    5  rank       what is worth asking next                    (code)
    6  navigate   reply, questions, proposed focus             (agent)
    7  store      pending questions, transcript                (code)

**A turn works on a copy.** :func:`run_turn` never touches the session it is
given; it returns a new one, or raises :class:`TurnRejected` having changed
nothing. That is how "reject the turn, no state change" is kept: there is no
half-applied turn to undo, because nothing is applied until the copy is returned.

What each failure does:

==============================  ==============================================
Interpreter cannot answer       Turn rejected. The user is asked to resend.
Extractor runs out of attempts  Turn continues on the previous graph. The
                                statements are queued for the next turn, and
                                the reply says the flow was not updated.
Navigator cannot answer         Turn continues. The reply is the top
                                candidate's own checklist question.
The API refuses a request       Turn rejected. The user can retry.
==============================  ==============================================

The asymmetry is deliberate. Without the interpreter's reading there is nothing
to apply, so the turn has no content. Without a patch or a worded reply there
still is: the user's statements are recorded and a sensible question exists.
"""

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agents.extractor import Correction, ExtractionOutcome, check, extract_patch
from agents.interpreter import InterpretResult, interpret
from agents.navigator import NavigatorResult, navigate
from extractors.conversation import ConversationFactory
from extractors.errors import ModelUnavailableError, SchemaCallError
from knowledge.loader import DomainKnowledge
from knowledge.schemas import MAIN_SCOPE, TopicStatus
from session.candidates import TOP, Candidate, rank_candidates
from session.focus import accept_focus, entering_focus, valid_scope
from session.ledger import (
    OpenItem,
    TopicUpdate,
    apply_applicability,
    apply_updates,
    initial_ledger,
    ledger_findings,
    link_nodes,
    mark_asked,
    open_items,
)
from session.models import (
    UNKNOWN_SCOPE,
    AskedQuestion,
    GraphVersion,
    LaneStatus,
    LearnedTerm,
    Message,
    Phase,
    QuestionKind,
    Role,
    Session,
    SessionLane,
    Statement,
    StatementOrigin,
    StepTiming,
    TurnStatus,
    UnknownTerm,
)
from session.patch import empty_graph
from session.statements import split
from validators.report import Finding, FindingCode
from validators.session_checks import normalise

logger = logging.getLogger(__name__)

Progress = Callable[[TurnStatus], None]
"""Called as a turn enters each step, so a caller can say what is happening."""

MAX_QUESTIONS = 3

RESEND = "I couldn't read that message. Nothing was changed; please send it again."
NOTHING_TO_READ = "That description is empty. Paste a description of the process to begin."
NOT_UPDATED = "The flow wasn't updated this turn. Your answer was kept and will be applied on the next turn."
FALLBACK_ACK = "Thanks, I've recorded that."
NOTHING_LEFT = "There's nothing further I need to ask. You can finish whenever you're ready."


class TurnRejected(Exception):
    """A turn that changed nothing. The message is a sentence for the user."""


@dataclass(frozen=True)
class TurnInput:
    """What the user sent."""

    description: str | None = None
    """The first description. Set on turn 1 only."""
    message: str | None = None
    hint: str | None = None
    """What a quick reply means, when the message was one."""
    item_key: str | None = None
    """An open item the user chose to answer at close-out."""


def new_session(session_id: str, domain: DomainKnowledge) -> Session:
    """A session before anything has been said.

    It starts with one lane: a placeholder for whatever system does the
    program's automated work, standing in the process's default persona. No
    client is chosen, so the session cannot know that system's name -- but
    unattributed work has to go somewhere from the first turn, and a lane whose
    name says it is unconfirmed is honest about that where a guessed name would
    not be.

    Args:
        session_id: The id to give it.
        domain: The knowledge base for the process the session is about.

    Returns:
        The session, with an empty graph and an untouched ledger.
    """
    session = Session(id=session_id, process_id=domain.process.id, graph=empty_graph(domain.process.id))
    session.lanes.append(
        SessionLane(name=session.default_lane, persona=domain.process.default_persona, status=LaneStatus.PLACEHOLDER)
    )
    session.ledger = initial_ledger(domain)
    return session


def run_turn(
    session: Session,
    domain: DomainKnowledge,
    turn_input: TurnInput,
    *,
    conversations: ConversationFactory,
    max_attempts: int,
    progress: Progress | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Session:
    """Run one turn of the conversation.

    Args:
        session: The session as it stands. Never modified.
        domain: The knowledge base for the session's process.
        turn_input: What the user sent.
        conversations: Where the three agents' models come from.
        max_attempts: The extractor's attempt budget, first attempt included.
        progress: Notified as each step begins.
        clock: A monotonic clock, injected so timings can be tested.

    Returns:
        The session after the turn: a new object, ready to be saved.

    Raises:
        TurnRejected: If the turn could not be carried out. Nothing changed.
    """
    working = session.model_copy(deep=True)
    working.turn += 1
    first = turn_input.description is not None
    text = (turn_input.description if first else turn_input.message) or ""
    timings: list[StepTiming] = []

    if working.phase is Phase.CLOSING and not first:
        # Answering something at close-out reopens the conversation.
        working.phase = Phase.PROBING
    if turn_input.item_key:
        working.pending = _question_for_item(working, domain, turn_input.item_key)

    _say(progress, TurnStatus.INTERPRETING)
    statements = tuple(split(text)) if first else ()
    if not text.strip() or (first and not statements):
        raise TurnRejected(NOTHING_TO_READ)
    started = clock()
    try:
        reading = interpret(
            working,
            domain,
            conversations=conversations,
            statements=statements,
            message=None if first else text,
            hint=turn_input.hint,
        )
    except SchemaCallError as error:
        logger.warning("turn %d: the interpreter could not answer: %s", working.turn, error)
        raise TurnRejected(RESEND) from error
    except ModelUnavailableError as error:
        raise TurnRejected(str(error)) from error
    timings.append(StepTiming(step="interpreter", seconds=clock() - started))

    applied = _apply(working, domain, reading, text, statements)

    _say(progress, TurnStatus.EXTRACTING)
    outcome: ExtractionOutcome | None = None
    if _worth_extracting(working, reading, applied, quick_reply=turn_input.hint is not None):
        try:
            outcome = extract_patch(
                working,
                domain,
                applied.statement_ids,
                applied.corrections,
                conversations=conversations,
                max_attempts=max_attempts,
                clock=clock,
            )
        except ModelUnavailableError as error:
            raise TurnRejected(str(error)) from error
        timings.extend(outcome.timings)
        working.graph = outcome.graph
        learn_lanes(working)
        if outcome.updated:
            working.retry_statement_ids = []
        else:
            working.retry_statement_ids = list(dict.fromkeys([*working.retry_statement_ids, *applied.statement_ids]))

    working.ledger = link_nodes(working.ledger, working.graph)
    resolution = _resolution(working, domain, outcome)
    working.versions.append(
        GraphVersion(
            turn=working.turn,
            patch=outcome.patch if outcome else None,
            updated=outcome.updated if outcome else True,
            attempts=outcome.attempts if outcome else 0,
            structural=outcome.structural if outcome else (),
            resolution=resolution,
        )
    )

    ranked = rank_candidates(working, domain)

    _say(progress, TurnStatus.NAVIGATING)
    closing_items = open_items(working, domain) if working.phase is Phase.CLOSING else ()
    started = clock()
    answer = _navigate(working, domain, ranked, resolution, closing_items, reading.meta, conversations)
    timings.append(StepTiming(step="navigator", seconds=clock() - started))

    questions = _questions(working, domain, answer, ranked)
    reply = _reply(working, answer, closing_items, domain)
    working.focus = accept_focus(
        answer.focus if answer else None,
        working,
        domain,
        ranked,
        requested=applied.requested_focus,
        scopes_raised_this_turn=applied.scopes,
    )
    if working.phase is Phase.DESCRIBING:
        working.phase = Phase.PROBING
    if (
        working.phase is Phase.PROBING
        and answer is not None
        and answer.propose_close
        and not any(candidate.rank <= 6 and not candidate.skip_offer for candidate in ranked)
    ):
        working.phase = Phase.CLOSING

    _store(working, text, reply, questions, timings)
    return working


def run_close(
    session: Session,
    domain: DomainKnowledge,
    *,
    conversations: ConversationFactory,
    progress: Progress | None = None,
) -> Session:
    """Enter close-out: stop asking, and say what is still open.

    No interpreter and no extractor: nothing was said, so there is nothing to
    read or apply. The navigator words the list; if it cannot, code does.

    Args:
        session: The session as it stands. Never modified.
        domain: The knowledge base.
        conversations: Where the navigator's model comes from.
        progress: Notified as the step begins.

    Returns:
        The session in the closing phase, with the open items listed in a new
        assistant message.

    Raises:
        TurnRejected: If the API refused the request. Nothing changed.
    """
    working = session.model_copy(deep=True)
    working.phase = Phase.CLOSING
    _say(progress, TurnStatus.NAVIGATING)
    items = open_items(working, domain)
    resolution = working.versions[-1].resolution if working.versions else ()
    answer = _navigate(working, domain, [], resolution, items, None, conversations)

    working.pending = []
    working.transcript.append(
        Message(role=Role.ASSISTANT, text=_reply(working, answer, items, domain), turn=max(working.turn, 1))
    )
    working.turn_status = TurnStatus.IDLE
    working.turn_error = None
    working.updated_at = datetime.now(UTC)
    return working


# ── step 2: apply ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Applied:
    """What applying the interpreter's reading produced, for the steps after it."""

    statement_ids: tuple[str, ...]
    corrections: tuple[Correction, ...]
    requested_focus: str | None
    scopes: frozenset[str]


def _apply(
    working: Session,
    domain: DomainKnowledge,
    reading: InterpretResult,
    text: str,
    statements: Sequence[str],
) -> _Applied:
    """Fold the interpreter's reading into the session. Every state change of step 2 is here."""
    id_of = _add_statements(working, domain, reading, text, statements)

    def ids(refs: Iterable[int]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(id_of[ref] for ref in refs if ref in id_of))

    updates = [
        TopicUpdate(
            topic_id=item.topic_id,
            status=TopicStatus(item.status),
            statement_ids=ids(item.statement_refs),
            note=item.note,
        )
        for item in reading.topic_updates
        if domain.topic(item.topic_id) is not None
    ]
    for fact in reading.facts:
        working.facts[fact.fact] = fact.value
        screening = next((topic for topic in domain.checklist.topics if topic.sets_fact is fact.fact), None)
        if screening is not None and not any(update.topic_id == screening.id for update in updates):
            # The answer to a screening question settles its topic whichever way it goes.
            status = TopicStatus.PRESENT if fact.value else TopicStatus.CONFIRMED_ABSENT
            updates.append(TopicUpdate(topic_id=screening.id, status=status, statement_ids=ids(fact.statement_refs)))

    working.ledger = apply_updates(working.ledger, updates, working.pending)
    working.ledger = apply_applicability(working.ledger, domain, working.facts)

    _apply_lanes(working, domain, reading, ids)
    _apply_terms(working, domain, reading, id_of)

    requested = reading.focus_request if valid_scope(domain, reading.focus_request) else working.requested_focus
    working.requested_focus = requested
    working.focus = entering_focus(working, domain)
    working.requested_focus = None
    if reading.meta == "done":
        working.phase = Phase.CLOSING

    new_ids = tuple(id_of.values())
    return _Applied(
        statement_ids=new_ids,
        corrections=tuple(
            Correction(statement_ids=ids(item.statement_refs), description=item.description)
            for item in reading.corrections
        ),
        requested_focus=requested if valid_scope(domain, requested) else None,
        scopes=frozenset(
            statement.scope for statement in working.corpus if statement.id in new_ids and statement.scope != MAIN_SCOPE
        ),
    )


def _add_statements(
    working: Session,
    domain: DomainKnowledge,
    reading: InterpretResult,
    text: str,
    statements: Sequence[str],
) -> dict[int, str]:
    """Append this turn's statements to the corpus.

    On the first turn the statements are the ones code split, and the reading
    only classifies them by number. On later turns the interpreter split the
    message itself, so each statement's text is checked against the message: a
    statement that is not the user's own words is replaced by the whole message
    rather than trusted, since statement text is what quotes are verified
    against.

    Returns:
        The interpreter's statement number -> the id the statement was given.
    """
    scopes = {*domain.process.scopes, UNKNOWN_SCOPE}
    by_index = {item.index: item for item in reading.statements}
    pending = {question.id for question in working.pending}
    touched: dict[int, list[str]] = {}
    for update in reading.topic_updates:
        for ref in update.statement_refs:
            touched.setdefault(ref, []).append(update.topic_id)

    if statements:
        planned: list[tuple[int, str, str | None]] = [(index, raw, None) for index, raw in enumerate(statements, 1)]
        origin = StatementOrigin.INITIAL_DESCRIPTION
    else:
        whole = text.strip()
        message = normalise(whole)
        planned = [
            (
                item.index,
                item.raw_text.strip() if item.raw_text.strip() and normalise(item.raw_text) in message else whole,
                item.restatement,
            )
            for item in sorted(reading.statements, key=lambda item: item.index)
        ] or [(1, whole, None)]
        origin = StatementOrigin.ANSWER

    id_of: dict[int, str] = {}
    for index, raw, restatement in planned:
        item = by_index.get(index)
        topic_ids = [*(item.topic_ids if item else ()), *touched.get(index, ())]
        statement = Statement(
            id=f"s_{len(working.corpus) + 1:04d}",
            origin=origin,
            turn=working.turn,
            raw_text=raw,
            restatement=restatement or None,
            question_id=item.question_id if item and item.question_id in pending else None,
            topic_ids=tuple(dict.fromkeys(t for t in topic_ids if domain.topic(t) is not None)),
            scope=item.scope if item and item.scope in scopes else MAIN_SCOPE,
        )
        working.corpus.append(statement)
        id_of[index] = statement.id
    return id_of


def _apply_lanes(
    working: Session,
    domain: DomainKnowledge,
    reading: InterpretResult,
    ids: Callable[[Iterable[int]], tuple[str, ...]],
) -> None:
    """Learn lanes, and resolve the placeholder once the automation system has a name.

    A lane the interpreter proposes is usable at once: waiting for confirmation
    would leave the extractor nowhere to put work the user has already
    attributed. A persona that is not in the knowledge base is dropped, not
    trusted.
    """

    def persona(name: str | None) -> str | None:
        return name if name in domain.personas else None

    for lane in reading.new_lanes:
        existing = _lane_named(working, lane.name)
        if existing is None:
            working.lanes.append(
                SessionLane(
                    name=lane.name.strip(),
                    persona=persona(lane.persona),
                    description=lane.description.strip(),
                    evidence=ids(lane.statement_refs),
                )
            )
        else:
            _update_lane(working, existing, persona(lane.persona), lane.description, ids(lane.statement_refs))
    for update in reading.lane_updates:
        existing = _lane_named(working, update.name)
        if existing is not None:
            _update_lane(working, existing, persona(update.persona), update.description, ids(update.statement_refs))

    if reading.default_lane is not None:
        name = reading.default_lane.name.strip()
        existing = _lane_named(working, name)
        if existing is None:
            working.lanes.append(
                SessionLane(
                    name=name,
                    persona=domain.process.default_persona,
                    evidence=ids(reading.default_lane.statement_refs),
                    status=LaneStatus.CONFIRMED,
                )
            )
            resolve_default_lane(working, name)
        elif existing.status is not LaneStatus.PLACEHOLDER:
            resolve_default_lane(working, existing.name)

    placeholder = working.lane(working.default_lane)
    if placeholder is not None and placeholder.status is LaneStatus.PLACEHOLDER:
        learned = next(
            (
                lane
                for lane in working.lanes
                if lane.persona == domain.process.default_persona and lane.status is not LaneStatus.PLACEHOLDER
            ),
            None,
        )
        if learned is not None:
            resolve_default_lane(working, learned.name)


def resolve_default_lane(session: Session, name: str) -> None:
    """Make a learned lane the default, and retire the placeholder.

    Every step that sat in the placeholder moves to the named lane: they were
    put there because nobody was named, and now the system that does unnamed
    work has a name.

    Args:
        session: The session to change in place.
        name: A lane already in ``session.lanes``.
    """
    old = session.default_lane
    if old == name or session.lane(name) is None:
        return
    session.default_lane = name
    old_lane = session.lane(old)
    if old_lane is None or old_lane.status is not LaneStatus.PLACEHOLDER:
        return
    session.graph = session.graph.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"actor": name}) if node.actor == old else node for node in session.graph.nodes
            )
        }
    )
    session.lanes = [lane for lane in session.lanes if lane.name != old]


def learn_lanes(session: Session) -> tuple[str, ...]:
    """Add a lane for every actor the graph uses that the session has not learned.

    The extractor is offered the session's lanes, and told to use the user's own
    name for anyone a statement attributes work to who is not among them. When
    it does, that is not a defect to repair: it is a lane nobody has described
    yet. It is added as ``proposed`` with no persona, which is exactly the state
    :mod:`session.candidates` turns into a question -- "what is X, and what part
    does it play?" -- so the user confirms it on the next turn.

    Args:
        session: The session to change in place, its graph already updated.

    Returns:
        The names added, in the order the graph first uses them.
    """
    known = {lane.name for lane in session.lanes}
    added: dict[str, list[str]] = {}
    for node in session.graph.nodes:
        if node.actor and node.actor not in known:
            added.setdefault(node.actor, []).extend(ref.statement_id for ref in node.evidence)
    for name, statement_ids in added.items():
        session.lanes.append(SessionLane(name=name, evidence=tuple(dict.fromkeys(statement_ids))))
    return tuple(added)


def _lane_named(session: Session, name: str) -> SessionLane | None:
    """A lane by name, ignoring case and surrounding space: 'the psm' and 'PSM' are one lane."""
    wanted = name.strip().casefold()
    return next((lane for lane in session.lanes if lane.name.casefold() == wanted), None)


def _update_lane(
    session: Session, lane: SessionLane, persona: str | None, description: str | None, evidence: tuple[str, ...]
) -> None:
    if lane.status is LaneStatus.PLACEHOLDER:
        return
    added = (description or "").strip()
    combined = lane.description if not added or added in lane.description else f"{lane.description} {added}".strip()
    changed = lane.model_copy(
        update={
            "persona": persona or lane.persona,
            "description": combined,
            "evidence": tuple(dict.fromkeys((*lane.evidence, *evidence))),
            # Naming a lane's persona is what settles it; until then it stays proposed.
            "status": LaneStatus.CONFIRMED if (persona or lane.persona) else lane.status,
        }
    )
    session.lanes = [changed if item.name == lane.name else item for item in session.lanes]


def _apply_terms(working: Session, domain: DomainKnowledge, reading: InterpretResult, id_of: dict[int, str]) -> None:
    """Record terms the user explained, and terms worth asking about."""
    for learned in reading.learned_terms:
        working.glossary = [item for item in working.glossary if item.term.casefold() != learned.term.casefold()]
        working.glossary.append(
            LearnedTerm(
                term=learned.term.strip(),
                meaning=learned.meaning.strip(),
                evidence=tuple(id_of[ref] for ref in learned.statement_refs if ref in id_of),
            )
        )

    known = {term.casefold() for term in domain.glossary}
    known |= {alias.casefold() for entry in domain.glossary.values() for alias in entry.aliases}
    known |= {item.term.casefold() for item in working.glossary}
    known |= {lane.name.casefold() for lane in working.lanes}
    working.unknown_terms = [item for item in working.unknown_terms if item.term.casefold() not in known]
    already = {item.term.casefold() for item in working.unknown_terms}
    for unknown in reading.unknown_terms:
        key = unknown.term.strip().casefold()
        if key and key not in known and key not in already and unknown.statement_ref in id_of:
            working.unknown_terms.append(
                UnknownTerm(term=unknown.term.strip(), first_statement_id=id_of[unknown.statement_ref])
            )
            already.add(key)


# ── steps 3 to 7 ─────────────────────────────────────────────────────────────


def _worth_extracting(working: Session, reading: InterpretResult, applied: _Applied, *, quick_reply: bool) -> bool:
    """Whether this turn said anything that could change the flow.

    "Not sure yet" and a question about the session describe no process, so
    calling the extractor on them would spend a model call to be told nothing
    changed. Statements still waiting from a failed turn always earn a call.
    """
    if working.retry_statement_ids or applied.corrections:
        return True
    if quick_reply or not applied.statement_ids:
        return False
    return not (reading.meta is not None and not reading.topic_updates)


def _resolution(working: Session, domain: DomainKnowledge, outcome: ExtractionOutcome | None) -> tuple[Finding, ...]:
    """This turn's open points: the graph's own, and covered topics no step rests on."""
    graph_findings = outcome.resolution if outcome else check(working.graph, working, domain).resolution
    unlinked = tuple(
        finding
        for finding in ledger_findings(working.ledger, domain)
        if finding.code is FindingCode.TOPIC_WITHOUT_NODES
    )
    return (*graph_findings, *unlinked)


def _navigate(
    working: Session,
    domain: DomainKnowledge,
    ranked: Sequence[Candidate],
    resolution: Sequence[Finding],
    closing_items: Sequence[OpenItem],
    meta: str | None,
    conversations: ConversationFactory,
) -> NavigatorResult | None:
    """Ask the navigator, or return None so the caller falls back.

    Raises:
        TurnRejected: If the API refused the request.
    """
    try:
        return navigate(
            working,
            domain,
            ranked[:TOP],
            conversations=conversations,
            findings=resolution,
            open_items=closing_items,
            meta=meta,
        )
    except SchemaCallError as error:
        logger.warning("turn %d: the navigator could not answer; falling back: %s", working.turn, error)
        return None
    except ModelUnavailableError as error:
        raise TurnRejected(str(error)) from error


def _questions(
    working: Session, domain: DomainKnowledge, answer: NavigatorResult | None, ranked: Sequence[Candidate]
) -> list[AskedQuestion]:
    """The questions to show, checked against the candidates they claim to come from.

    The navigator words a question; code decides what it is *about*. A question
    naming a candidate takes that candidate's kind, steps, scope and subject, so
    a mis-copied id cannot attach an answer to the wrong topic. One of the
    navigator's own keeps only the topic and step ids that exist.
    """
    if working.phase is Phase.CLOSING:
        return []
    by_id = {candidate.id: candidate for candidate in ranked}
    askable = [candidate for candidate in ranked if not candidate.skip_offer]
    nodes = {node.id for node in working.graph.nodes}
    drafts: list[tuple[Candidate | None, str, tuple[str, ...], tuple[str, ...], str]] = []

    for question in (answer.questions if answer else ())[:MAX_QUESTIONS]:
        candidate = by_id.get(question.candidate_id or "")
        topics = tuple(topic for topic in question.topic_ids if domain.topic(topic) is not None)
        if candidate is None:
            scope = question.scope if valid_scope(domain, question.scope) else working.focus
            drafts.append((None, question.text, topics, tuple(n for n in question.node_ids if n in nodes), scope))
        elif not candidate.skip_offer:
            merged = tuple(dict.fromkeys((*candidate.topic_ids, *topics)))
            drafts.append((candidate, question.text, merged, candidate.node_ids, candidate.scope))

    if not drafts and askable:
        top = askable[0]
        drafts.append((top, top.ask, top.topic_ids, top.node_ids, top.scope))

    return [
        AskedQuestion(
            id="pending",
            turn=working.turn,
            kind=candidate.kind if candidate else QuestionKind.SUGGESTED,
            topic_ids=topics,
            node_ids=node_ids,
            scope=scope,
            text=text.strip(),
            subject=candidate.subject if candidate else None,
        )
        for candidate, text, topics, node_ids, scope in drafts
    ]


def _reply(
    working: Session, answer: NavigatorResult | None, closing_items: Sequence[OpenItem], domain: DomainKnowledge
) -> str:
    """The message the user reads: the navigator's, or one code can stand behind."""
    if answer is not None:
        return answer.reply.strip()
    parts = [FALLBACK_ACK]
    if not working.flow_updated:
        parts.append(NOT_UPDATED)
    if working.phase is Phase.CLOSING:
        parts.append(closing_summary(closing_items, domain))
    return " ".join(parts)


def closing_summary(items: Sequence[OpenItem], domain: DomainKnowledge) -> str:
    """The open items in words, grouped by flow. What the navigator's listing falls back to."""
    if not items:
        return NOTHING_LEFT
    lines = ["Here is what is still open:"]
    for scope in domain.process.scopes:
        mine = [item.text for item in items if item.scope == scope]
        if mine:
            lines.append(f"{domain.process.scope_label(scope)}: " + "; ".join(mine) + ".")
    lines.append("You can answer any of these, or accept them as open and finish.")
    return " ".join(lines)


def _question_for_item(working: Session, domain: DomainKnowledge, key: str) -> list[AskedQuestion]:
    """The pending question that stands for an open item the user chose to answer."""
    item = next((item for item in open_items(working, domain) if item.key == key), None)
    if item is None:
        return working.pending
    topic = domain.topic(item.topic_id) if item.topic_id else None
    working.question_count += 1
    return [
        AskedQuestion(
            id=f"q_{working.question_count:04d}",
            turn=working.turn,
            kind=QuestionKind.GAP if item.topic_id else QuestionKind.STRUCTURAL,
            topic_ids=(item.topic_id,) if item.topic_id else (),
            node_ids=(item.node_id,) if item.node_id else (),
            scope=item.scope,
            text=topic.ask if topic else item.text,
        )
    ]


def _store(
    working: Session, text: str, reply: str, questions: Sequence[AskedQuestion], timings: Sequence[StepTiming]
) -> None:
    """Step 7: number the questions, record them as asked, and write the transcript."""
    numbered = []
    for question in questions:
        working.question_count += 1
        numbered.append(question.model_copy(update={"id": f"q_{working.question_count:04d}"}))

    working.pending = numbered
    working.ledger = mark_asked(working.ledger, numbered)
    asked_terms = {question.subject for question in numbered if question.kind is QuestionKind.TERM}
    working.unknown_terms = [
        term.model_copy(update={"asked_count": term.asked_count + 1}) if term.term in asked_terms else term
        for term in working.unknown_terms
    ]
    working.transcript.append(Message(role=Role.USER, text=text.strip(), turn=working.turn))
    working.transcript.append(Message(role=Role.ASSISTANT, text=reply, turn=working.turn, questions=tuple(numbered)))
    working.versions[-1] = working.versions[-1].model_copy(update={"timings": tuple(timings)})
    working.turn_status = TurnStatus.IDLE
    working.turn_error = None
    working.updated_at = datetime.now(UTC)


def _say(progress: Progress | None, status: TurnStatus) -> None:
    if progress is not None:
        progress(status)
