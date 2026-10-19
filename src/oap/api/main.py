"""Application factory of the explorer API.

``app`` is the default application, configured from the environment, for ``uvicorn
oap.api.main:app``. Tests and ``scripts/export_openapi.py`` call ``create_app``.
"""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.gzip import GZipMiddleware

from oap import __version__
from oap.api.errors import install_error_handlers
from oap.api.models import ErrorBody, HealthResponse
from oap.api.routers import landscape, meta, spreads
from oap.api.settings import ApiSettings
from oap.api.static import SPAStaticFiles
from oap.api.store import GoldStore

GZIP_MINIMUM_SIZE = 1000
"""Responses below this size in bytes are not compressed."""


def _operation_id(route: APIRoute) -> str:
    """Use the route name as the OpenAPI operation id.

    Args:
        route: The route.

    Returns:
        The ``name=`` given to the route decorator, such as ``getChain``.
    """
    return route.name


def openapi_text(app: FastAPI) -> str:
    """Render the OpenAPI document of an application as the committed file's text.

    Args:
        app: The application.

    Returns:
        The document as JSON with sorted keys, two-space indent and a final newline, which
        is what ``apps/web/openapi.json`` holds.
    """
    document: dict[str, Any] = app.openapi()
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build the explorer application.

    Args:
        settings: Settings; read from the environment when None.

    Returns:
        The application with GZip, optional CORS, the routers, ``/healthz`` and, when
        ``web_dist/index.html`` exists, the built web app mounted at ``/`` last.
    """
    cfg = settings if settings is not None else ApiSettings.from_env()
    app = FastAPI(
        title="oap explorer API",
        version=__version__,
        description="Read-only API over the gold tables: distributions, heatmaps and spreads.",
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = cfg
    store = GoldStore(cfg)
    app.state.store = store
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_SIZE)
    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET"],
            allow_headers=["*"],
            expose_headers=["Retry-After", "X-OAP-Data-Stale"],
        )
    install_error_handlers(app, retry_after_s=cfg.retry_after_s)
    for module in (meta, landscape, spreads):
        app.include_router(module.router)

    @app.get("/healthz", name="healthz", response_model=HealthResponse, tags=["meta"])
    def healthz() -> HealthResponse:
        """Report the state of the service and of the database file.

        Returns:
            Always HTTP 200: ``db`` says whether the file can be read.
        """
        return store.health()

    index = cfg.web_dist / "index.html"
    if index.is_file():
        app.mount("/", SPAStaticFiles(directory=cfg.web_dist, html=True), name="web")
    else:

        @app.get("/", include_in_schema=False)
        def root() -> JSONResponse:
            """Say that the web app is not built.

            Returns:
                A 404 whose detail names the command that builds it.
            """
            body = ErrorBody(
                detail="The web app is not built: run make web-build.", code="not_found"
            )
            return JSONResponse(status_code=404, content=body.model_dump(mode="json"))

    return app


app = create_app()
