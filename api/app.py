"""The HTTP surface: four endpoints, and no logic of its own.

Runs are started and polled rather than awaited, because a run takes a minute or
two and a request held open that long is dropped by the host in front of it. So:
``POST /runs`` returns an id, ``GET /runs/{id}`` says how it is going, and the
payload arrives on the poll that finds it finished.

Everything the pipeline can go wrong with is already an exception that says what
happened, so the handlers here translate rather than diagnose. The model and the
layouter are constructor arguments -- the same seam the CLI stages use -- so the
whole service can be exercised with no API key, no network and no Node.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import pipeline
from api.runs import Run, RunStore
from bpmn.autolayout import Layouter
from extractors.process import ModelCall
from ir.process_config import list_processes
from utils.settings import load_api_settings

logger = logging.getLogger(__name__)

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
"""Where ``pipelines/site.py`` writes the page. Served only if it is there."""


class RunRequest(BaseModel):
    """What the page posts to start a run."""

    process: str = Field(description="The process folder name, e.g. 'enrollment'.")
    source: str = Field(description="The written process description to extract from.")


def create_app(
    *,
    call: ModelCall | None = None,
    layout: Layouter | None = None,
    processes_root: Path = pipeline.DEFAULT_PROCESSES_ROOT,
    site_dir: Path = SITE_DIR,
) -> FastAPI:
    """Build the service.

    Args:
        call: The model. Defaults to one built from the environment per run.
        layout: The layouter. Defaults to the pinned CLI.
        processes_root: Where the process folders live.
        site_dir: A built static site to serve at ``/``. Mounted only if it
            exists, which is what makes the one-URL deployment possible: the
            same service can host the page it answers.

    Returns:
        The application.
    """
    settings = load_api_settings()
    store = RunStore()
    app = FastAPI(title="Process Flow Generator", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness, and the wake-up call the page makes on load."""
        return {"status": "ok"}

    @app.get("/processes")
    def processes() -> list[dict[str, str]]:
        """The processes that can be run, for the picker."""
        return [
            {"name": process.name, "display_name": process.display_name} for process in list_processes(processes_root)
        ]

    @app.post("/runs", status_code=202)
    def start(request: RunRequest) -> dict[str, str]:
        """Queue a run and answer with its id."""
        source = request.source.strip()
        if not source:
            raise HTTPException(status_code=422, detail="Paste a process description first.")
        if len(source) > settings.max_source_chars:
            raise HTTPException(
                status_code=413,
                detail=(f"That description is {len(source):,} characters; the limit is {settings.max_source_chars:,}."),
            )
        if request.process not in {process.name for process in list_processes(processes_root)}:
            raise HTTPException(status_code=404, detail=f"There is no '{request.process}' process.")

        run = store.start(
            lambda progress: pipeline.run(
                request.process,
                source,
                processes_root,
                call=call,
                layout=layout,
                progress=progress,
            )
        )
        return {"id": run.id}

    @app.get("/runs/{run_id}")
    def state(run_id: str) -> dict[str, object]:
        """How a run is going, and its payload once it is done."""
        run = store.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="That run is not in flight. Start another.")
        return _state(run)

    if site_dir.is_dir():
        # Last, so it claims only the paths the API did not. With this mounted
        # the page and the service share an origin and CORS stops mattering.
        app.mount("/", StaticFiles(directory=site_dir, html=True), name="site")

    return app


def _state(run: Run) -> dict[str, object]:
    """One run, as the page reads it."""
    return {
        "id": run.id,
        "status": run.status,
        "label": run.label,
        "detail": run.detail,
        "result": run.result,
    }


app = create_app()
"""The instance uvicorn serves."""
