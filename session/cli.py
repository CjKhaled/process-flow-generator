"""A conversation in the terminal.

The fastest way to try the conversational stage 1 with a real model: no page, no
server, the same pipeline. ``start`` reads a description, runs the first turn and
drops into a chat loop; ``resume`` picks a stored session back up::

    uv run python -m session.cli start --process enrollment_and_intake --input description.md
    uv run python -m session.cli resume --session 3f9a...

Inside the loop a line is an answer, unless it begins with a slash:

==================  =========================================================
``/focus <scope>``  Discuss ``main`` or a subprocess next.
``/state``          Print the flow, the lanes and coverage.
``/close``          Stop asking, and list what is still open.
``/accept``         Accept what is open and write the final BPMN and HTML.
``/quit``           Leave. The session is saved after every turn.
==================  =========================================================

This module prints and reads; it decides nothing. Every turn goes through
:func:`session.orchestrator.run_turn`, exactly as the HTTP service's does.
"""

import argparse
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from agents.navigator import graph_summary
from extractors.conversation import ConversationFactory
from extractors.model import StrandsConversationFactory
from knowledge.loader import DomainKnowledge, load_domain
from session.focus import valid_scope
from session.ledger import coverage
from session.models import Phase, Role, Session
from session.orchestrator import TurnInput, TurnRejected, new_session, run_close, run_turn
from session.store import FileSessionStore, SessionNotFound, SessionStore
from utils.logs import configure_logging
from utils.settings import load_session_settings, load_settings

Reader = Callable[[str], str]


def main(argv: list[str] | None = None, *, read: Reader = input) -> int:
    """Command-line entry point.

    Args:
        argv: The arguments, or None for the process's own.
        read: Where answers come from. Injected so the loop can be scripted.

    Returns:
        0 on success, 1 if the first turn was rejected, 2 if the process, the
        input or the configuration could not be read.
    """
    parser = argparse.ArgumentParser(description="Hold a conversation about a process in the terminal.")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Begin a session from a written description.")
    start.add_argument("--process", required=True, help="Knowledge folder name, e.g. 'enrollment_and_intake'.")
    start.add_argument("--input", required=True, type=Path, help="A file holding the description.")
    start.add_argument("--no-chat", action="store_true", help="Run the first turn and stop.")
    resume = commands.add_parser("resume", help="Carry on a stored session.")
    resume.add_argument("--session", required=True, help="The session id.")
    args = parser.parse_args(argv)

    configure_logging()

    directories = load_session_settings()
    store = FileSessionStore(directories.sessions_dir)
    try:
        settings = load_settings()
    except ValidationError as error:
        missing = ", ".join(str(item["loc"][0]) for item in error.errors())
        print(f"error: configuration is incomplete ({missing})", file=sys.stderr)
        print("set ANTHROPIC_API_KEY in the environment or in a .env file.", file=sys.stderr)
        return 2
    conversations = StrandsConversationFactory(settings)

    try:
        if args.command == "start":
            domain = load_domain(args.process)
            description = args.input.read_text(encoding="utf-8")
            session = new_session(uuid.uuid4().hex[:12], domain)
            store.create(session)
            print(f"session {session.id}")
            try:
                session = _turn(
                    session,
                    domain,
                    TurnInput(description=description),
                    conversations,
                    store,
                    settings.max_extraction_attempts,
                )
            except TurnRejected as error:
                print(f"error: {error}", file=sys.stderr)
                return 1
            print_state(session, domain)
            if args.no_chat:
                return 0
        else:
            session = store.load(args.session)
            domain = load_domain(session.process_id)
            print_reply(session)
    except SessionNotFound:
        print(f"error: there is no session '{args.session}'", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    chat(session, domain, conversations, store, settings.max_extraction_attempts, read)
    return 0


def chat(
    session: Session,
    domain: DomainKnowledge,
    conversations: ConversationFactory,
    store: SessionStore,
    max_attempts: int,
    read: Reader = input,
) -> Session:
    """Read answers until the user leaves or the session completes.

    Args:
        session: The session to carry on.
        domain: Its knowledge base.
        conversations: Where the agents' models come from.
        store: Where each turn's result is saved.
        max_attempts: The extractor's attempt budget.
        read: Where answers come from.

    Returns:
        The session as it stood when the loop ended.
    """
    while session.phase is not Phase.COMPLETE:
        try:
            line = read("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            break
        if line == "/state":
            print_state(session, domain)
            continue
        if line.startswith("/focus"):
            scope = line.removeprefix("/focus").strip()
            if not valid_scope(domain, scope):
                print(f"no such scope; choose one of: {', '.join(domain.process.scopes)}")
                continue
            session.requested_focus = scope
            store.save(session)
            print(f"next turn will discuss: {domain.process.scope_label(scope)}")
            continue
        try:
            if line == "/close":
                session = run_close(session, domain, conversations=conversations)
                store.save(session)
                print_reply(session)
            elif line == "/accept":
                # Imported here: close-out needs stage 2 and 3, which a chat does not.
                from session.closeout import finalise

                session = finalise(session, domain, store)
                store.save(session)
                for flow in session_flows(store, session):
                    print(f"wrote {flow}")
            else:
                session = _turn(session, domain, TurnInput(message=line), conversations, store, max_attempts)
                print_summary(session, domain)
        except TurnRejected as error:
            print(f"! {error}")
        except (RuntimeError, ValueError) as error:
            print(f"! could not finish: {error}")
    return session


def session_flows(store: SessionStore, session: Session) -> list[Path]:
    """The folders close-out wrote for a session."""
    flows = store.path_for_outputs(session.id, "main").parent
    return sorted(path for path in flows.glob("*") if path.is_dir())


def _turn(
    session: Session,
    domain: DomainKnowledge,
    turn_input: TurnInput,
    conversations: ConversationFactory,
    store: SessionStore,
    max_attempts: int,
) -> Session:
    """Run one turn, save it, and print the reply."""
    updated = run_turn(
        session,
        domain,
        turn_input,
        conversations=conversations,
        max_attempts=max_attempts,
        progress=lambda status: print(f"  ... {status}", file=sys.stderr),
    )
    store.save(updated)
    print_reply(updated)
    return updated


def print_reply(session: Session) -> None:
    """The latest assistant message and the questions under it."""
    last = next((message for message in reversed(session.transcript) if message.role is Role.ASSISTANT), None)
    if last is None:
        return
    print(f"\n{last.text}")
    for number, question in enumerate(last.questions, start=1):
        print(f"  {number}. {question.text}")
    if not session.flow_updated:
        print("  (the flow wasn't updated this turn)")


def print_summary(session: Session, domain: DomainKnowledge) -> None:
    """One line on the graph and one per scope on coverage, after each turn."""
    open_nodes = sum(node.status == "needs_clarification" for node in session.graph.nodes)
    print(
        f"\n[turn {session.turn} | focus: {session.focus} | phase: {session.phase} | "
        f"{len(session.graph.nodes)} steps, {len(session.graph.edges)} connections, {open_nodes} open]"
    )
    for scope in coverage(session, domain):
        counts = scope["counts"]
        assert isinstance(counts, dict)
        listed = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        print(f"  {scope['label']}: {listed}")


def print_state(session: Session, domain: DomainKnowledge) -> None:
    """The flow, the lanes and coverage, in full."""
    print("\n" + graph_summary(session.graph, domain))
    print("\nLanes:")
    for lane in session.lanes:
        default = " (default)" if lane.name == session.default_lane else ""
        print(f"  - {lane.name} [{lane.persona or 'role not known'}; {lane.status}]{default} {lane.description}")
    if session.unknown_terms:
        print("Unexplained terms: " + ", ".join(term.term for term in session.unknown_terms))
    print_summary(session, domain)


if __name__ == "__main__":
    raise SystemExit(main())
