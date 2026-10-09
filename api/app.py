"""The application: a health check, the conversation's endpoints, and the page.

Three things and no logic. :mod:`api.sessions` holds every endpoint that does
anything; this module builds the app around it, adds ``/health``, and serves the
built page at ``/`` when there is one.

When ``PFG_ACCESS_PASSWORD`` is set, all of it sits behind one shared password,
asked for by the browser. That is a door, not accounts: it keeps a stranger from
spending the API key, and says nothing about who inside is who.

The model, the layouter, the viewer's files and the session store are arguments
to :func:`create_app`, so the whole service is exercised in tests with no API
key, no network and no Node.
"""

import base64
import binascii
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.sessions import create_session_router
from bpmn.autolayout import Layouter
from extractors.conversation import ConversationFactory
from render.assets import ViewerAssets
from session.store import FileSessionStore, SessionStore
from utils.logs import configure_logging
from utils.settings import load_api_settings, load_session_settings

logger = logging.getLogger(__name__)

HEALTH_PATH = "/health"

CHALLENGE = {"WWW-Authenticate": 'Basic realm="Process Flow Generator", charset="UTF-8"'}
"""What makes a browser ask for the password instead of showing a bare error."""

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
"""Where the page is built to. Served at ``/`` only if it is there."""


def create_app(
    *,
    conversations: ConversationFactory | None = None,
    session_store: SessionStore | None = None,
    layout: Layouter | None = None,
    assets: ViewerAssets | None = None,
    domain_dir: Path | None = None,
    frontend_dir: Path = FRONTEND_DIR,
) -> FastAPI:
    """Build the service.

    Args:
        conversations: The agents' models. Defaults to Strands, built from the
            environment per turn.
        session_store: Where sessions are kept. Defaults to files under
            ``PFG_SESSIONS_DIR``.
        layout: The layouter, for a session's final diagrams. Defaults to the
            pinned CLI.
        assets: The viewer's files, for a session's final pages. Defaults to the
            built bundle.
        domain_dir: The knowledge base. Defaults to ``PFG_DOMAIN_DIR``.
        frontend_dir: The built page, served at ``/``. Mounted only if it
            exists, so the API runs without it -- which is how the tests and a
            ``vite dev`` session both use it.

    Returns:
        The application.
    """
    settings = load_api_settings()
    app = FastAPI(title="Process Flow Generator", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    password = settings.access_password.get_secret_value() if settings.access_password else None
    if password:

        @app.middleware("http")
        async def require_password(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            """Turn away any request that does not carry the shared password.

            Everything, with two exceptions. The health check, because the host
            calls it and cannot authenticate; and a CORS preflight, which a
            browser sends without credentials by design and which carries no
            data either way.
            """
            if request.url.path == HEALTH_PATH or request.method == "OPTIONS" or _authorised(request, password):
                return await call_next(request)
            return Response("A password is required.", status_code=401, headers=CHALLENGE)

    else:
        logger.warning(
            "PFG_ACCESS_PASSWORD is not set: the service is open to anyone who can reach it, "
            "and every turn spends the API key. Fine on a laptop; set it anywhere else."
        )

    @app.get(HEALTH_PATH)
    def health() -> dict[str, str]:
        """Liveness, and something cheap to wake a sleeping instance with."""
        return {"status": "ok"}

    if session_store is None:
        # The default store, so this is a real start-up and not a test with a store
        # of its own: put back any shipped session the disk does not have.
        directories = load_session_settings()
        files = FileSessionStore(directories.sessions_dir)
        restored = files.restore_seeds(directories.seed_sessions_dir)
        if restored:
            logger.info("restored %d seed session(s): %s", len(restored), ", ".join(restored))
        session_store = files

    app.include_router(
        create_session_router(
            store=session_store,
            conversations=conversations,
            layout=layout,
            assets=assets,
            domain_dir=domain_dir,
        )
    )

    if frontend_dir.is_dir():
        # Last, so it claims only the paths the API did not. With this mounted the
        # page and the service share an origin and CORS stops mattering.
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="page")
    else:
        logger.warning("no built page at %s; run `npm run build --prefix frontend` to serve one at /", frontend_dir)

    return app


def _authorised(request: Request, password: str) -> bool:
    """Whether a request carries HTTP Basic credentials with the shared password.

    The username is ignored: there are no accounts, only a door. Compared in
    constant time, so how long a refusal takes says nothing about how close the
    guess was.
    """
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        _, _, given = base64.b64decode(encoded, validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return secrets.compare_digest(given.encode("utf-8"), password.encode("utf-8"))


# This module is what uvicorn is pointed at, so importing it *is* starting the service:
# the one place logging is configured on import rather than from a ``main``.
configure_logging()

app = create_app()
"""The instance uvicorn serves."""
