# Read-only API Task 2 Report

## Status

Completed the catalog-backed loopback API boundary. Cursor pagination and
allowlisted artifact retrieval remain intentionally unavailable until their
separate prerequisite tasks provide their required safety controls.

## Scope

- Added typed `RunListResponse` and public `ApiError` models.
- Added `create_trajectory_app(catalog, cursor_codec)` with only the currently
  supportable catalog routes: `GET /api/runs` and `GET /api/runs/{analysis_id}`.
- Disabled FastAPI docs and retained the planned `/api/openapi.json` endpoint.
- Applied CSP, `nosniff`, frame denial, no-referrer, and no-store headers to
  every HTTP response; no CORS middleware is installed.
- Added a loopback-only Uvicorn configuration builder. It permits only
  `127.0.0.1`, `::1`, and `localhost`, defaults to `127.0.0.1:8765`, and
  disables access logs.

## TDD evidence

RED:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q
4 failed: ModuleNotFoundError: grid_agent.trajectory.api.app
```

GREEN:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_catalog.py packages/grid-agent/tests/trajectory/api/test_app.py packages/grid-agent/tests/trajectory/api/test_server.py -q
16 passed
```

## Verification

```text
uv run --project packages/grid-agent ruff check [Task 2 files]
All checks passed!

uv run --project packages/grid-agent pyright [Task 2 files]
0 errors, 0 warnings, 0 informations

git diff --check
passed
```

## Boundary note

The factory keeps its approved `cursor_codec` parameter but does not invoke it
until the signed cursor/paging task exists. No paging, context, or artifact
route is registered now, so unavailable capabilities return the framework 404
rather than exposing an unsound fallback.

## Review follow-up: safe unexpected errors

Resolved the high-severity review finding for unexpected catalog and response
serialization failures. Both now return the fixed typed envelope:

```json
{"code":"internal_error","message":"an unexpected error occurred"}
```

The error response applies the fixed security headers itself. This is required
because FastAPI's top-level exception handling can render an exception response
outside the application middleware path. The existing middleware continues to
apply the same headers to successful and framework-generated responses. The
specific `RunNotFoundError` mapping remains a typed 404.

Follow-up TDD evidence:

```text
RED: unexpected catalog exception produced FastAPI's plain-text 500 body;
     after adding the generic handler, it still lacked x-content-type-options,
     proving the middleware ordering gap.
GREEN: uv run --project packages/grid-agent pytest
       packages/grid-agent/tests/trajectory/api/test_app.py -q
       7 passed

uv run --project packages/grid-agent ruff check [review follow-up files]
All checks passed!

uv run --project packages/grid-agent pyright [review follow-up files]
0 errors, 0 warnings, 0 informations
```
