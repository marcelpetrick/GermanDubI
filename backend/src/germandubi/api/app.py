"""The FastAPI application.

Heavy media and ML work never runs here. Requests queue jobs; the worker process does the
work. That keeps the browser responsive during a long run and is the one deliberate process
boundary in this architecture (ADR-0002).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from germandubi.api.errors import install_error_handlers
from germandubi.api.routers import events, media, meta, pipeline, projects, segments
from germandubi.composition import Application, build_application, configure_logging
from germandubi.config import Settings, get_settings
from germandubi.version import build_info

__all__ = ["create_app"]

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

DESCRIPTION = """
Turn an English single-narrator video into an editable, synchronized German dub.

**The workflow**

1. `POST /projects` with a YouTube URL.
2. `POST /projects/{id}/analyze` to read the source cheaply.
3. `POST /projects/{id}/runs` to produce the dub.
4. Follow `GET /projects/{id}/events` for progress.
5. Review and correct segments; each correction reports exactly what became stale.
6. `GET /projects/{id}/download` for the finished file.

The API version is versioned independently of the build version and of the project file
format. Do not infer one from another.
"""


def create_app(
    settings: Settings | None = None,
    *,
    application: Application | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: Settings to use; read from the environment when omitted.
        application: A pre-built application, injected by tests so they can share wiring.
        frontend_dist: A compiled frontend bundle to serve, for the production-like
            single-process deployment.

    Returns:
        The configured application.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)
    wired = application or build_application(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Attach the wired application for the process's lifetime."""
        app.state.application = wired
        report = wired.registry.report()
        if report.missing_required:
            logger.warning(
                "missing required tools: %s. Run `germandubi doctor`.",
                ", ".join(report.missing_required),
            )
        logger.info(
            "GermanDubI %s ready at http://%s:%d",
            build_info().display,
            resolved.host,
            resolved.port,
        )
        yield
        if application is None:
            wired.dispose()

    app = FastAPI(
        title="GermanDubI",
        summary="German Dub Interface - English videos to German ones, made easy.",
        description=DESCRIPTION,
        version=build_info().version,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        contact={"name": "GermanDubI", "url": "https://github.com/marcelpetrick/GermanDubI"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        # The browser cannot read Content-Range on a cross-origin request without this,
        # which breaks seeking in the dev-server setup.
        expose_headers=["content-range", "accept-ranges", "content-length"],
    )

    install_error_handlers(app)

    for router in (
        meta.router,
        projects.router,
        pipeline.router,
        segments.router,
        events.router,
        media.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    if frontend_dist is not None and frontend_dist.exists():
        _serve_frontend(app, frontend_dist)

    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the compiled single-page app.

    Any path that is not an API route falls through to ``index.html``, so client-side
    routing works on a hard refresh instead of returning a 404.
    """
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve a static file, falling back to the SPA entry point."""
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
