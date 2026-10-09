"""The conversation's HTTP surface: start a session, answer, look, finish.

Start-and-poll. A turn is three model calls and takes longer than a host will
hold a request open, so every endpoint that starts work answers ``202`` at once,
and ``GET /sessions/{id}`` is what the page polls to find out how it is going and
to collect the result. Polling is also what lets the page say which step is
running instead of spinning at nothing.

State lives in the session file, written after every turn. This module keeps no
session of its own -- only the set of ids with a turn in flight, which is what
makes a second message to a busy session a ``409`` instead of a race.

**Turns are serialised per session.** Two sessions may run at once; one session
never runs two turns, because the second would start from a state the first is
about to replace.

It takes its outside dependencies as arguments -- the model, the layouter, the
viewer's files, the store -- so the whole surface is
tested with no key, no network and no Node. And it holds no logic: every turn is
:func:`session.orchestrator.run_turn`, the same call the CLI makes.

Everything the reader can read is worded here, in Python: the status line, the
quick replies, the error sentence. The page prints what it is given.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, ValidationError

from agents.extractor import DEFAULT_MAX_ATTEMPTS
from bpmn.autolayout import Layouter, LayoutError
from extractors.conversation import ConversationFactory
from extractors.model import StrandsConversationFactory
from ir.process_config import OUTPUTS_DIRNAME
from knowledge.loader import DomainKnowledge, list_domain_processes, load_domain
from render.assets import AssetError, ViewerAssets
from session.closeout import DOWNLOADS, PAGE_FILENAME, NothingToDraw, finalise, list_outputs
from session.focus import valid_scope
from session.ledger import coverage, open_items
from session.models import Phase, Session, TurnStatus
from session.orchestrator import NOT_UPDATED, Progress, TurnInput, TurnRejected, new_session, run_close, run_turn
from session.slicing import SliceError
from session.store import SessionNotFound, SessionStore
from session.views import session_views
from utils.logs import trace_context
from utils.settings import load_api_settings, load_settings

logger = logging.getLogger(__name__)

WORKERS = 4
"""How many sessions may have a turn running at once."""

STATUS_LABELS = {
    TurnStatus.IDLE: "",
    TurnStatus.QUEUED: "Waiting to start…",
    TurnStatus.INTERPRETING: "Reading your answer…",
    TurnStatus.EXTRACTING: "Updating the flow…",
    TurnStatus.NAVIGATING: "Thinking of the next questions…",
    TurnStatus.FINALISING: "Drawing the final diagrams…",
    TurnStatus.FAILED: "That turn did not complete.",
}
"""What each status says on the page. Written here so the browser only prints it."""

_IN_FLIGHT = frozenset(
    {
        TurnStatus.QUEUED,
        TurnStatus.INTERPRETING,
        TurnStatus.EXTRACTING,
        TurnStatus.NAVIGATING,
        TurnStatus.FINALISING,
    }
)

QUICK_REPLIES = {
    "not_sure": ("Not sure yet", "The user does not know the answer yet and would have to check. Defer the topic."),
    "not_applicable": (
        "Not part of our process",
        "The user is saying this does not happen in their program. It is confirmed absent, not unknown.",
    ),
}
"""Each quick reply: the words sent as the user's message, and what the interpreter is told it means.

Sent as text as well as a flag, so the transcript reads naturally and the
interpreter handles a pressed button and a typed "not sure" the same way.
"""

INTERRUPTED = "The service restarted while that turn was running. Nothing was changed; please send it again."
BROKEN = "Something went wrong inside the pipeline. Nothing was changed; the service log has the details."
UNCONFIGURED = "The service is not configured to reach a model. Nothing was changed."
BUSY = "A turn is already running for this session. Wait for it to finish."
FINISHED = "This session is finished. Answer something to reopen it first."
REOPEN = "This session is finished. Sending an answer reopens it; finish again to redraw the diagrams."
STALE = "These diagrams were drawn before your latest answers. Finish again to redraw them."


class StartRequest(BaseModel):
    """What the page posts to begin a session."""

    process_id: str = Field(description="The knowledge folder name, e.g. 'enrollment_and_intake'.")
    description: str = Field(description="The written process description to begin from.")


class MessageRequest(BaseModel):
    """One answer from the user."""

    text: str = Field(default="", description="What the user typed. May be empty when a quick reply is given.")
    quick_reply: str | None = Field(default=None, description="'not_sure', 'not_applicable', or null.")
    question_id: str | None = Field(default=None, description="The pending question this answers, if one was chosen.")
    item_key: str | None = Field(default=None, description="An open item being answered at close-out.")


class FocusRequest(BaseModel):
    """The user opening a flow in the page."""

    focus: str = Field(description="'main' or a subprocess id.")


Work = Callable[[Session, Progress], Session]


class TurnRunner:
    """Runs turns in the background, one at a time per session.

    Thread-safe: HTTP threads ask whether a session is busy while workers
    finish turns, so the set of running ids is only touched under a lock.
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="pfg-turn")

    def is_running(self, session_id: str) -> bool:
        """Whether a turn is in flight for this session, in this process."""
        with self._lock:
            return session_id in self._running

    def submit(self, session: Session, work: Work, status: TurnStatus = TurnStatus.QUEUED) -> bool:
        """Queue a turn.

        Args:
            session: The session the turn starts from.
            work: The turn. Given the session and a progress callback, it returns
                the session to store.
            status: What to show while it waits for a worker.

        Returns:
            False if the session already has a turn running, in which case
            nothing was queued.
        """
        with self._lock:
            if session.id in self._running:
                return False
            self._running.add(session.id)
        self._mark(session.id, status, error=None)
        logger.info("session %s: work queued (%s)", session.id, status)
        self._pool.submit(self._execute, session.id, work)
        return True

    def _execute(self, session_id: str, work: Work) -> None:
        with trace_context(session=session_id):
            self._run(session_id, work)

    def _run(self, session_id: str, work: Work) -> None:
        started = time.perf_counter()
        logger.info("session %s: a worker picked the work up", session_id)
        try:
            updated = work(self._store.load(session_id), lambda status: self._mark(session_id, status, error=None))
        except TurnRejected as error:
            logger.warning("session %s: turn rejected, nothing changed: %s", session_id, error)
            self._mark(session_id, TurnStatus.FAILED, error=str(error))
        except ValidationError as error:  # Before ValueError, which it subclasses.
            missing = ", ".join(str(item["loc"][0]) for item in error.errors())
            self._mark(session_id, TurnStatus.FAILED, error=f"{UNCONFIGURED} ({missing})")
        except (LayoutError, AssetError, SliceError, NothingToDraw, ValueError) as error:
            logger.warning("session %s: close-out failed: %s", session_id, error)
            self._mark(session_id, TurnStatus.FAILED, error=f"The final diagrams could not be produced: {error}")
        except Exception:
            # Whatever went wrong, the browser is entitled to hear about it rather
            # than poll a turn that never moves again. This is the worker thread:
            # there is nobody above it to catch anything it lets past.
            logger.exception("session %s: turn failed", session_id)
            self._mark(session_id, TurnStatus.FAILED, error=BROKEN)
        else:
            self._store.save(updated)
            logger.info(
                "session %s: saved after %.1fs | turn %d, phase %s",
                session_id,
                time.perf_counter() - started,
                updated.turn,
                updated.phase,
            )
        finally:
            with self._lock:
                self._running.discard(session_id)

    def _mark(self, session_id: str, status: TurnStatus, *, error: str | None) -> None:
        """Set the stored session's status and nothing else.

        The turn itself works on a copy, so this is the only thing written while
        one is in flight -- which is why a failed turn leaves the session exactly
        as it was, with a sentence saying why.
        """
        session = self._store.load(session_id)
        session.turn_status = status
        session.turn_error = error
        self._store.save(session)
        logger.info("session %s: status -> %s%s", session_id, status, f" ({error})" if error else "")


def create_session_router(
    *,
    store: SessionStore,
    conversations: ConversationFactory | None = None,
    layout: Layouter | None = None,
    assets: ViewerAssets | None = None,
    domain_dir: Path | None = None,
) -> APIRouter:
    """Build the session endpoints.

    Args:
        store: Where sessions are kept.
        conversations: The agents' models. Defaults to Strands, built from the
            environment when a turn begins -- so a service with no key still
            starts, and says what is wrong on the first turn.
        layout: The layouter for close-out. Defaults to the pinned CLI.
        assets: The viewer's files for close-out. Defaults to the built bundle.
        domain_dir: The knowledge base. Defaults to ``PFG_DOMAIN_DIR``.

    Returns:
        A router to include in the application.
    """
    router = APIRouter()
    runner = TurnRunner(store)
    limits = load_api_settings()

    def domain_for(process_id: str) -> DomainKnowledge:
        return load_domain(process_id, domain_dir)

    def seam() -> tuple[ConversationFactory, int]:
        """The agents' models and the extractor's attempt budget, read when a turn starts.

        An injected factory comes with the fallback budget: the configured one
        lives in settings that need a key, and a caller who injects a model is
        one who has none.
        """
        if conversations is not None:
            return conversations, DEFAULT_MAX_ATTEMPTS
        settings = load_settings()
        return StrandsConversationFactory(settings), settings.max_extraction_attempts

    def load(session_id: str) -> Session:
        try:
            return store.load(session_id)
        except SessionNotFound:
            raise HTTPException(status_code=404, detail="There is no such session.") from None

    def start_turn(session: Session, turn_input: TurnInput) -> None:
        def work(current: Session, progress: Progress) -> Session:
            factory, max_attempts = seam()
            return run_turn(
                current,
                domain_for(current.process_id),
                turn_input,
                conversations=factory,
                max_attempts=max_attempts,
                progress=progress,
            )

        if not runner.submit(session, work):
            raise HTTPException(status_code=409, detail=BUSY)

    @router.get("/processes")
    def processes() -> list[dict[str, str]]:
        """The processes a conversation can be held about, for the picker."""
        return [{"id": name, "display_name": display} for name, display in list_domain_processes(domain_dir)]

    @router.post("/sessions", status_code=202)
    def start(request: StartRequest) -> dict[str, str]:
        """Create a session and queue its first turn."""
        description = request.description.strip()
        if not description:
            raise HTTPException(status_code=422, detail="Paste a process description first.")
        if len(description) > limits.max_source_chars:
            raise HTTPException(
                status_code=413,
                detail=f"That description is {len(description):,} characters; the limit is {limits.max_source_chars:,}.",
            )
        try:
            domain = domain_for(request.process_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail=f"There is no '{request.process_id}' process.") from None

        session = new_session(uuid.uuid4().hex[:16], domain)
        store.create(session)
        logger.info(
            "session %s created for '%s' from a %d-char description", session.id, request.process_id, len(description)
        )
        start_turn(session, TurnInput(description=description))
        return {"session_id": session.id}

    @router.get("/sessions/{session_id}")
    def state(session_id: str) -> dict[str, object]:
        """Everything the page shows: transcript, questions, coverage, views."""
        # Asked before the session is read, and the order matters. A turn that ends between
        # the two reads would otherwise be seen as "status says in flight, nobody running",
        # which is how a restart looks. This way round the worst case is one extra poll.
        running = runner.is_running(session_id)
        session = load(session_id)
        return _state(session, domain_for(session.process_id), store, running=running)

    @router.post("/sessions/{session_id}/messages", status_code=202)
    def message(session_id: str, request: MessageRequest) -> dict[str, str]:
        """Queue a turn for one answer. On a finished session, that reopens it."""
        session = load(session_id)
        quick = QUICK_REPLIES.get(request.quick_reply or "")
        if request.quick_reply and quick is None:
            raise HTTPException(status_code=422, detail=f"There is no '{request.quick_reply}' quick reply.")
        text = request.text.strip() or (quick[0] if quick else "")
        if not text:
            raise HTTPException(status_code=422, detail="Type an answer first.")
        if len(text) > limits.max_source_chars:
            raise HTTPException(status_code=413, detail="That answer is too long.")

        hints = [quick[1]] if quick else []
        if request.question_id and any(question.id == request.question_id for question in session.pending):
            hints.append(f"The user chose to answer question {request.question_id}.")
        start_turn(session, TurnInput(message=text, hint=" ".join(hints) or None, item_key=request.item_key))
        return {"session_id": session.id}

    @router.post("/sessions/{session_id}/focus")
    def focus(session_id: str, request: FocusRequest) -> dict[str, str]:
        """Record a flow the user opened. Honoured on the next turn."""
        session = load(session_id)
        if not valid_scope(domain_for(session.process_id), request.focus):
            raise HTTPException(status_code=422, detail=f"There is no '{request.focus}' flow.")
        if runner.is_running(session_id):
            raise HTTPException(status_code=409, detail=BUSY)
        session.requested_focus = request.focus
        store.save(session)
        logger.info("session %s: the user opened '%s'; honoured on the next turn", session_id, request.focus)
        return {"focus": request.focus}

    @router.post("/sessions/{session_id}/close", status_code=202)
    def close(session_id: str) -> dict[str, str]:
        """Enter close-out: stop asking, and list what is still open."""
        session = load(session_id)
        _require_unfinished(session)

        def work(current: Session, progress: Progress) -> Session:
            factory, _ = seam()
            return run_close(current, domain_for(current.process_id), conversations=factory, progress=progress)

        if not runner.submit(session, work):
            raise HTTPException(status_code=409, detail=BUSY)
        return {"session_id": session.id}

    @router.post("/sessions/{session_id}/accept", status_code=202)
    def accept(session_id: str) -> dict[str, str]:
        """Accept what is still open and produce the final diagrams."""
        session = load(session_id)
        _require_unfinished(session)
        if not session.graph.nodes:
            raise HTTPException(status_code=409, detail="There is no flow to finish yet.")

        def work(current: Session, progress: Progress) -> Session:  # noqa: ARG001  # one step, already announced
            return finalise(current, domain_for(current.process_id), store, layout=layout, assets=assets)

        if not runner.submit(session, work, TurnStatus.FINALISING):
            raise HTTPException(status_code=409, detail=BUSY)
        return {"session_id": session.id}

    @router.get("/sessions/{session_id}/outputs")
    def outputs(session_id: str) -> list[dict[str, object]]:
        """The finished flows and the files each offers."""
        session = load(session_id)
        return list_outputs(session, domain_for(session.process_id), store)

    @router.get("/sessions/{session_id}/outputs/{flow}/{filename}")
    def download(session_id: str, flow: str, filename: str) -> FileResponse:
        """One finished file, as a download."""
        session = load(session_id)
        if filename not in DOWNLOADS:
            raise HTTPException(status_code=404, detail="There is no such file.")
        try:
            path = store.path_for_outputs(session.id, flow) / OUTPUTS_DIRNAME / filename
        except ValueError:
            raise HTTPException(status_code=404, detail="There is no such flow.") from None
        if not path.is_file():
            raise HTTPException(status_code=404, detail="That file has not been produced yet.")
        return FileResponse(path, filename=f"{flow}-{filename}")

    @router.get("/sessions/{session_id}/flows/{flow}/page", response_class=HTMLResponse)
    def flow_page(session_id: str, flow: str) -> HTMLResponse:
        """One finished flow's page, served to be looked at, not saved.

        The same ``diagram.html`` the download endpoint serves, without the
        header that makes a browser save it -- which is what lets the page show
        it in a frame. It is stage 3's own page, whole: its Edit mode, its
        questions panel and its zoom arrive with it and need nothing from here.
        """
        session = load(session_id)
        try:
            path = store.path_for_outputs(session.id, flow) / OUTPUTS_DIRNAME / PAGE_FILENAME
        except ValueError:
            raise HTTPException(status_code=404, detail="There is no such flow.") from None
        if not path.is_file():
            raise HTTPException(status_code=404, detail="That flow has not been drawn yet.")
        return HTMLResponse(path.read_text(encoding="utf-8"))

    return router


def _require_unfinished(session: Session) -> None:
    """Refuse to close or accept a session that is already finished.

    Only those two. A finished session still takes an answer, which reopens it;
    what it cannot do is be finished twice with nothing said in between, since
    that would redraw the same diagrams.
    """
    if session.phase is Phase.COMPLETE:
        raise HTTPException(status_code=409, detail=FINISHED)


def _state(session: Session, domain: DomainKnowledge, store: SessionStore, *, running: bool) -> dict[str, object]:
    """One session, as the page reads it.

    A status that says a turn is in flight when no worker holds one means the
    process restarted mid-turn. The turn's work was on a copy and is gone, so
    the session is exactly as it was before; the page is told that, rather than
    being left to poll a turn that will never finish.
    """
    process = domain.process
    status, error = session.turn_status, session.turn_error
    if status in _IN_FLIGHT and not running:
        status, error = TurnStatus.FAILED, INTERRUPTED

    personas = {persona_id: persona.name for persona_id, persona in domain.personas.items()}
    finished = list_outputs(session, domain, store)
    stale = bool(finished) and session.phase is not Phase.COMPLETE
    return {
        "id": session.id,
        "process_id": session.process_id,
        "process_name": process.display_name,
        "phase": session.phase,
        "focus": session.focus,
        "focus_label": process.scope_label(session.focus),
        "requested_focus": session.requested_focus,
        "turn": session.turn,
        "turn_status": status,
        "status_label": error if status is TurnStatus.FAILED and error else STATUS_LABELS[status],
        "running": running,
        "flow_updated": session.flow_updated,
        "notice": None if session.flow_updated else NOT_UPDATED,
        "transcript": [message.model_dump(mode="json") for message in session.transcript],
        "pending": [question.model_dump(mode="json") for question in session.pending],
        "quick_replies": [{"id": key, "label": label} for key, (label, _) in QUICK_REPLIES.items()],
        "lanes": [
            {
                "name": lane.name,
                "persona": personas.get(lane.persona or ""),
                "description": lane.description,
                "status": lane.status,
                "default": lane.name == session.default_lane,
            }
            for lane in session.lanes
        ],
        "coverage": coverage(session, domain),
        "views": [view.model_dump(mode="json") for view in session_views(session, domain)],
        "open_items": [
            {
                "key": item.key,
                "scope": item.scope,
                "scope_label": process.scope_label(item.scope),
                "kind": item.kind,
                "text": item.text,
            }
            for item in open_items(session, domain)
        ],
        # Listed whenever they exist, not only while the session is finished: a
        # reopened session still has the diagrams it was last finished with, and
        # the page says they are out of date rather than hiding them.
        "outputs": finished,
        "outputs_stale": stale,
        "outputs_notice": STALE if stale else None,
        "reopen_notice": REOPEN if session.phase is Phase.COMPLETE else None,
    }
