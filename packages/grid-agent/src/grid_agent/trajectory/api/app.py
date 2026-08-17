"""Read-only HTTP boundary for discovered trajectory runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from grid_agent.trajectory.api.artifacts import ArtifactAccessError, ArtifactGateway
from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec, CursorError, CursorExpectation, CursorState
from grid_agent.trajectory.api.models import ApiError, RunListResponse, RunSummary
from grid_agent.trajectory.api.paging import ProjectionPager, ProjectionRecordTooLarge
from grid_agent.trajectory.api.projection_pages import (
    ProjectionPageResponse,
    projection_page,
    public_context_frame,
)
from grid_agent.trajectory.agent_projection import execution_slice
from grid_agent.trajectory.business_projection import business_causal_rows
from grid_agent.trajectory.projection_models import (
    ExecutionSlice,
    LifecycleStatus,
    NodeSource,
    ProjectedRun,
)


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

_BUSINESS_PROJECTION_VERSION = "business-trajectory/1.1"


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


def create_trajectory_app(
    catalog: TrajectoryRunCatalog,
    cursor_codec: CursorCodec,
    *,
    static_root: Path | None = None,
) -> FastAPI:
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
        return _business_page(catalog.open(analysis_id), cursor, cursor_codec)

    @app.get("/api/runs/{analysis_id}/agent", response_model=ProjectionPageResponse)
    def agent_page(
        analysis_id: str,
        request: Request,
        cursor: str | None = Query(default=None, min_length=1, max_length=8_192),
        turn_id: str | None = Query(default=None, min_length=1, max_length=500),
        kind: Literal["turn", "step", "request", "retry", "response", "tool"]
        | None = Query(default=None),
        status: LifecycleStatus | None = Query(default=None),
        capability: str | None = Query(default=None, min_length=1, max_length=500),
        q: str | None = Query(default=None, min_length=1, max_length=200),
    ) -> ProjectionPageResponse:
        _reject_unknown_or_repeated_query(
            request,
            {"cursor", "turn_id", "kind", "status", "capability", "q"},
        )
        return projection_page(
            catalog.open(analysis_id),
            "agent",
            cursor,
            {
                "turn_id": turn_id,
                "kind": kind,
                "status": status,
                "capability": capability,
                "q": q,
            },
            cursor_codec,
        )

    @app.get("/api/runs/{analysis_id}/context")
    def context_view(
        analysis_id: str,
        request: Request,
        at_sequence: int | None = Query(default=None, ge=1),
        cursor: str | None = Query(default=None, min_length=1, max_length=8_192),
        from_sequence: int | None = Query(default=None, ge=1),
        to_sequence: int | None = Query(default=None, ge=1),
        from_revision: int | None = Query(default=None, ge=0),
        to_revision: int | None = Query(default=None, ge=0),
        changed: bool | None = Query(default=None),
        request_input: bool | None = Query(default=None),
    ) -> dict[str, Any]:
        _reject_unknown_or_repeated_query(
            request,
            {
                "at_sequence",
                "cursor",
                "from_sequence",
                "to_sequence",
                "from_revision",
                "to_revision",
                "changed",
                "request_input",
            },
        )
        projected = catalog.open(analysis_id)
        filters: dict[str, str | int | bool | None] = {
            "from_sequence": from_sequence,
            "to_sequence": to_sequence,
            "from_revision": from_revision,
            "to_revision": to_revision,
            "changed": changed,
            "request_input": request_input,
        }
        if at_sequence is not None:
            if cursor is not None or any(value is not None for value in filters.values()):
                raise _invalid_query("at_sequence")
            return _context_detail(
                projected,
                at_sequence,
                Path(catalog.runs_root) / projected.analysis_id,
            )
        return projection_page(
            projected, "context", cursor, filters, cursor_codec
        ).model_dump(mode="json")

    @app.get("/api/runs/{analysis_id}/execution", response_model=ExecutionSlice)
    def execution_frame(
        analysis_id: str, at_sequence: int = Query(ge=1)
    ) -> ExecutionSlice:
        return execution_slice(catalog.open(analysis_id), at_sequence)

    @app.get("/api/runs/{analysis_id}/evidence", response_model=ProjectionPageResponse)
    def evidence_page(
        analysis_id: str,
        request: Request,
        cursor: str | None = Query(default=None, min_length=1, max_length=8_192),
        kind: str | None = Query(default=None, min_length=1, max_length=100),
        source: NodeSource | None = Query(default=None),
        verification_status: Literal["verified", "unavailable"] | None = Query(
            default=None
        ),
        from_sequence: int | None = Query(default=None, ge=1),
        to_sequence: int | None = Query(default=None, ge=1),
        relevant_ref: str | None = Query(default=None, min_length=1, max_length=1_000),
        sort: Literal["producer_sequence", "verification_status"] | None = Query(
            default=None
        ),
    ) -> ProjectionPageResponse:
        _reject_unknown_or_repeated_query(
            request,
            {
                "cursor",
                "kind",
                "source",
                "verification_status",
                "from_sequence",
                "to_sequence",
                "relevant_ref",
                "sort",
            },
        )
        return projection_page(
            catalog.open(analysis_id),
            "evidence",
            cursor,
            {
                "kind": kind,
                "source": source,
                "verification_status": verification_status,
                "from_sequence": from_sequence,
                "to_sequence": to_sequence,
                "relevant_ref": relevant_ref,
                "sort": sort,
            },
            cursor_codec,
        )

    @app.get("/api/runs/{analysis_id}/artifacts/{artifact_ref}")
    def artifact(analysis_id: str, artifact_ref: str) -> Response:
        projected = catalog.open(analysis_id)
        run_root = Path(catalog.runs_root) / projected.analysis_id
        opened = ArtifactGateway(run_root, projected.artifacts).open(artifact_ref)
        response = Response(content=opened.content, media_type=opened.media_type)
        response.headers["Content-Disposition"] = f'attachment; filename="{opened.filename}"'
        return response

    mount_workbench(app, static_root or _packaged_static_root())
    return app


def _invalid_query(parameter: str) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("query", parameter),
                "msg": "request parameter combination is invalid",
                "input": None,
            }
        ]
    )


def _reject_unknown_or_repeated_query(
    request: Request, allowed: set[str]
) -> None:
    for parameter in request.query_params:
        if parameter not in allowed or len(request.query_params.getlist(parameter)) != 1:
            raise _invalid_query(parameter)


def _context_detail(
    projected: ProjectedRun, at_sequence: int, run_root: Path
) -> dict[str, Any]:
    frame = public_context_frame(
        projected, projected.context.at_sequence(at_sequence)
    )
    value = frame.model_dump(mode="json")
    value["request_input_available"] = frame.request_artifact_ref is not None
    value["request_input_unavailable_reason"] = (
        None if frame.request_artifact_ref is not None else frame.unavailable_reason
    )
    value["max_sequence"] = max(
        (item.source_sequence for item in projected.context.frames), default=0
    )
    value["request_input"] = _canonical_request_preview(
        projected, run_root, frame.request_artifact_ref
    )
    return value


def _canonical_request_preview(
    projected: ProjectedRun, run_root: Path, reference: str | None
) -> dict[str, Any] | None:
    if reference is None:
        return None
    record = projected.artifacts.records.get(reference)
    if record is None or record.verification_status != "verified":
        return None
    path = run_root / record.relative_path
    try:
        path.resolve(strict=True).relative_to(run_root.resolve(strict=True))
        content = path.read_bytes()
    except (OSError, ValueError):
        return None
    if record.sha256 != hashlib.sha256(content).hexdigest():
        return None
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if document.get("schema_version") != "grid-model-request-input/2.0":
        return None
    preview_keys = (
        "request_id",
        "request_index",
        "turn_id",
        "captured_at",
        "source_event_sequences",
        "context_revision",
        "context_state_hash",
        "runtime",
        "semantic_request",
        "semantic_request_sha256",
    )
    if not all(key in document for key in preview_keys):
        return None
    return {key: document[key] for key in preview_keys}


def _packaged_static_root() -> Path:
    return Path(__file__).resolve().parents[1] / "static"


def mount_workbench(app: FastAPI, static_root: Path) -> None:
    """Serve only the verified packaged SPA after every API route is registered."""
    index = static_root / "index.html"
    app_js = static_root / "assets" / "app.js"
    app_css = static_root / "assets" / "app.css"
    if not all(path.is_file() for path in (index, app_js, app_css)):
        raise RuntimeError("trajectory workbench assets are missing; run make build-workbench")

    app.mount(
        "/assets",
        StaticFiles(directory=static_root / "assets", check_dir=True),
        name="trajectory-assets",
    )

    @app.get("/{client_path:path}", include_in_schema=False)
    def spa(client_path: str) -> FileResponse:
        if client_path == "api" or client_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(index, media_type="text/html; charset=utf-8")


def _business_page(
    projected: ProjectedRun,
    cursor: str | None,
    cursor_codec: CursorCodec,
) -> ProjectionPageResponse:
    expectation = CursorExpectation(
        analysis_id=projected.analysis_id,
        view="business",
        source_fingerprint=projected.source_fingerprint,
        projection_version=_BUSINESS_PROJECTION_VERSION,
    )
    cursor_state = cursor_codec.decode(cursor, expectation) if cursor else None
    records = tuple(
        _ProjectionRecord(
            sequence=row.source_sequence,
            item=row.model_dump(mode="json"),
        )
        for row in business_causal_rows(projected.business)
    )
    page = ProjectionPager().page(records, cursor_state=cursor_state)
    older_cursor = (
        cursor_codec.encode(
            CursorState(
                analysis_id=projected.analysis_id,
                view="business",
                source_fingerprint=projected.source_fingerprint,
                projection_version=_BUSINESS_PROJECTION_VERSION,
                before_sequence=page.older_cursor,
            )
        )
        if page.older_cursor is not None
        else None
    )
    return ProjectionPageResponse(
        analysis_id=projected.analysis_id,
        items=tuple(record.item for record in page.items),
        older_cursor=older_cursor,
        newer_cursor=page.newer_cursor,
        first_sequence=page.first_sequence,
        last_sequence=page.last_sequence,
        has_older=page.has_older,
        encoded_bytes=page.encoded_bytes,
    )


__all__ = ["SECURITY_HEADERS", "create_trajectory_app", "mount_workbench"]
