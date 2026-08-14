"""Read-only HTTP boundary for discovered trajectory runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from grid_agent.trajectory.api.artifacts import ArtifactAccessError, ArtifactGateway
from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec, CursorError, CursorExpectation, CursorState
from grid_agent.trajectory.api.models import ApiError, RunListResponse, RunSummary
from grid_agent.trajectory.api.paging import ProjectionPager, ProjectionRecordTooLarge
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

_PROJECTION_VERSIONS = {
    "business": "business-trajectory/1.0",
    "agent": "agent-trajectory/1.0",
}


class ProjectionPageResponse(BaseModel):
    """The stable HTTP page envelope for either fixed projection view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[dict[str, Any], ...] = ()
    older_cursor: str | None = None
    newer_cursor: None = None
    first_sequence: int | None = Field(default=None, ge=1)
    last_sequence: int | None = Field(default=None, ge=1)
    has_older: bool
    encoded_bytes: int = Field(ge=0)


@dataclass(slots=True)
class _ProjectionRecord:
    sequence: int
    item: dict[str, Any]

    def model_dump(self, *, mode: str) -> object:
        del mode
        return self.item


def _api_error_response(status_code: int, code: str, message: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=ApiError(code=code, message=message).model_dump(mode="json"),
    )
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    return response


def create_trajectory_app(catalog: TrajectoryRunCatalog, cursor_codec: CursorCodec) -> FastAPI:
    """Create the fixed, local, read-only trajectory projection boundary."""
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
        return _api_error_response(
            status_code=404,
            code="run_not_found",
            message="trajectory run not found",
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        """Return a stable public envelope without exposing validation internals."""
        return _api_error_response(
            status_code=422,
            code="invalid_request",
            message="request parameters are invalid",
        )

    @app.exception_handler(CursorError)
    async def cursor_error(_: Request, exc: CursorError) -> JSONResponse:
        stale = "stale" in str(exc)
        return _api_error_response(
            status_code=409 if stale else 400,
            code="stale_cursor" if stale else "invalid_cursor",
            message="projection cursor is stale" if stale else "projection cursor is invalid",
        )

    @app.exception_handler(ProjectionRecordTooLarge)
    async def projection_too_large(
        _: Request, __: ProjectionRecordTooLarge
    ) -> JSONResponse:
        return _api_error_response(
            status_code=409,
            code="projection_corrupt",
            message="trajectory projection cannot be served",
        )

    @app.exception_handler(KeyError)
    async def context_not_available(_: Request, __: KeyError) -> JSONResponse:
        return _api_error_response(
            status_code=409,
            code="projection_corrupt",
            message="requested context frame is unavailable",
        )

    @app.exception_handler(ArtifactAccessError)
    async def artifact_access(_: Request, exc: ArtifactAccessError) -> JSONResponse:
        missing = str(exc) == "artifact is not registered"
        return _api_error_response(
            status_code=404 if missing else 403,
            code="artifact_not_found" if missing else "artifact_rejected",
            message="trajectory artifact not found" if missing else "trajectory artifact was rejected",
        )

    @app.exception_handler(Exception)
    async def internal_error(_: Request, __: Exception) -> JSONResponse:
        return _api_error_response(
            status_code=500,
            code="internal_error",
            message="an unexpected error occurred",
        )

    @app.get("/api/runs", response_model=RunListResponse)
    def list_runs() -> RunListResponse:
        return RunListResponse(items=catalog.list_runs())

    @app.get("/api/runs/{analysis_id}", response_model=RunSummary)
    def get_run(analysis_id: str) -> RunSummary:
        """Return only the bounded metadata already exposed by the catalogue."""
        for summary in catalog.list_runs():
            if summary.analysis_id == analysis_id:
                return summary
        raise RunNotFoundError(analysis_id)

    @app.get("/api/runs/{analysis_id}/business", response_model=ProjectionPageResponse)
    def business_page(
        analysis_id: str, cursor: str | None = Query(default=None)
    ) -> ProjectionPageResponse:
        return _page_view(catalog.open(analysis_id), "business", cursor, cursor_codec)

    @app.get("/api/runs/{analysis_id}/agent", response_model=ProjectionPageResponse)
    def agent_page(
        analysis_id: str, cursor: str | None = Query(default=None)
    ) -> ProjectionPageResponse:
        return _page_view(catalog.open(analysis_id), "agent", cursor, cursor_codec)

    @app.get("/api/runs/{analysis_id}/context")
    def context_frame(
        analysis_id: str, at_sequence: int = Query(ge=1)
    ) -> dict[str, Any]:
        projected = catalog.open(analysis_id)
        frame = projected.context.at_sequence(at_sequence)
        value = frame.model_dump(mode="json")
        value["max_sequence"] = max(
            (item.source_sequence for item in projected.context.frames), default=0
        )
        return value

    @app.get("/api/runs/{analysis_id}/artifacts/{artifact_ref}")
    def artifact(analysis_id: str, artifact_ref: str) -> Response:
        projected = catalog.open(analysis_id)
        run_root = Path(catalog.runs_root) / projected.analysis_id
        opened = ArtifactGateway(run_root, projected.artifacts).open(artifact_ref)
        response = Response(content=opened.content, media_type=opened.media_type)
        response.headers["Content-Disposition"] = f'attachment; filename="{opened.filename}"'
        return response

    return app


def _page_view(
    projected: ProjectedRun,
    view: Literal["business", "agent"],
    cursor: str | None,
    cursor_codec: CursorCodec,
) -> ProjectionPageResponse:
    expectation = CursorExpectation(
        analysis_id=projected.analysis_id,
        view=view,
        source_fingerprint=projected.source_fingerprint,
        projection_version=_PROJECTION_VERSIONS[view],
    )
    cursor_state = cursor_codec.decode(cursor, expectation) if cursor else None
    items = (
        projected.business.problems if view == "business" else projected.agent.turns
    )
    records = tuple(
        _ProjectionRecord(
            sequence=max(item.source_sequences),
            item=item.model_dump(mode="json") | {"source_sequence": max(item.source_sequences)},
        )
        for item in items
    )
    page = ProjectionPager().page(records, cursor_state=cursor_state)
    older_cursor = (
        cursor_codec.encode(
            CursorState(
                analysis_id=projected.analysis_id,
                view=view,
                source_fingerprint=projected.source_fingerprint,
                projection_version=_PROJECTION_VERSIONS[view],
                before_sequence=page.older_cursor,
            )
        )
        if page.older_cursor is not None
        else None
    )
    return ProjectionPageResponse(
        items=tuple(record.item for record in page.items),
        older_cursor=older_cursor,
        newer_cursor=page.newer_cursor,
        first_sequence=page.first_sequence,
        last_sequence=page.last_sequence,
        has_older=page.has_older,
        encoded_bytes=page.encoded_bytes,
    )


__all__ = ["SECURITY_HEADERS", "create_trajectory_app"]
