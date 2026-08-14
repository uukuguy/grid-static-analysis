"""Read-only HTTP boundary for discovered trajectory runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.models import ApiError, RunListResponse
from grid_agent.trajectory.projection_models import ProjectedRun


SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_trajectory_app(catalog: TrajectoryRunCatalog, cursor_codec: object) -> FastAPI:
    """Create the catalog-only read boundary available at this implementation stage.

    ``cursor_codec`` is deliberately retained in the public factory contract for
    the later page routes. This task does not expose views or artifacts until
    their signed-paging and allowlisted-artifact dependencies exist.
    """
    del cursor_codec
    app = FastAPI(
        title="grid-agent trajectory",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(RunNotFoundError)
    async def run_not_found(_: Request, __: RunNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ApiError(code="run_not_found", message="trajectory run not found").model_dump(
                mode="json"
            ),
        )

    @app.get("/api/runs", response_model=RunListResponse)
    def list_runs() -> RunListResponse:
        return RunListResponse(items=catalog.list_runs())

    @app.get("/api/runs/{analysis_id}", response_model=ProjectedRun)
    def get_run(analysis_id: str) -> ProjectedRun:
        return catalog.open(analysis_id)

    return app


__all__ = ["SECURITY_HEADERS", "create_trajectory_app"]
