"""The application: a health check, the conversation's endpoints, and the page.

Three things and no logic. :mod:`api.sessions` holds every endpoint that does
anything; this module builds the app around it, adds ``/health``, and serves the
built page at ``/`` when there is one.

The model, the layouter, the viewer's files and the session store are arguments
to :func:`create_app`, so the whole service is exercised in tests with no API
key, no network and no Node.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
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

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness, and something cheap to wake a sleeping instance with."""
        return {"status": "ok"}

    app.include_router(
        create_session_router(
            store=session_store or FileSessionStore(load_session_settings().sessions_dir),
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


# This module is what uvicorn is pointed at, so importing it *is* starting the service:
# the one place logging is configured on import rather than from a ``main``.
configure_logging()

app = create_app()
"""The instance uvicorn serves."""
