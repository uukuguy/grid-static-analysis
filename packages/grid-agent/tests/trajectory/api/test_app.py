from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.models import RunSummary


class StubCatalog:
    def list_runs(self) -> tuple[RunSummary, ...]:
        return (
            RunSummary(
                analysis_id="analysis-test",
                status="completed",
                source_kind="native",
                started_at="2026-08-14T08:18:22Z",
                turn_count=1,
                last_sequence=900,
                replay_trusted_through=900,
            ),
        )

    def open(self, analysis_id: str) -> object:
        assert analysis_id == "analysis-test"
        return cast(object, SimpleNamespace())


def create_test_app() -> FastAPI:
    from grid_agent.trajectory.api.app import create_trajectory_app

    return create_trajectory_app(
        cast(TrajectoryRunCatalog, StubCatalog()), cast(object, SimpleNamespace())
    )


def test_api_lists_runs_with_a_typed_response() -> None:
    response = TestClient(create_test_app()).get("/api/runs")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "analysis_id": "analysis-test",
                "status": "completed",
                "source_kind": "native",
                "started_at": "2026-08-14T08:18:22Z",
                "turn_count": 1,
                "last_sequence": 900,
                "replay_trusted_through": 900,
                "diagnostic": None,
            }
        ]
    }


def test_api_has_no_mutation_routes() -> None:
    client = TestClient(create_test_app())

    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/runs/analysis-test").status_code == 405


def test_every_response_has_browser_security_headers_without_cors() -> None:
    response = TestClient(create_test_app()).get("/api/runs")

    assert response.headers["content-security-policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in response.headers


def test_openapi_exposes_only_get_methods() -> None:
    app = create_test_app()

    methods = {
        method
        for path in app.openapi()["paths"].values()
        for method in path
    }

    assert methods == {"get"}


def test_unexpected_catalog_failure_returns_safe_typed_internal_error() -> None:
    class FailingCatalog(StubCatalog):
        def list_runs(self) -> tuple[RunSummary, ...]:
            raise RuntimeError("/operator/private/runs database password=secret")

    from grid_agent.trajectory.api.app import SECURITY_HEADERS, create_trajectory_app

    app = create_trajectory_app(
        cast(TrajectoryRunCatalog, FailingCatalog()), cast(object, SimpleNamespace())
    )
    response = TestClient(app, raise_server_exceptions=False).get("/api/runs")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "an unexpected error occurred",
    }
    assert "private" not in response.text
    assert "password" not in response.text
    assert {name.lower(): value for name, value in SECURITY_HEADERS.items()}.items() <= response.headers.items()


def test_response_serialization_failure_returns_safe_typed_internal_error() -> None:
    response = TestClient(create_test_app(), raise_server_exceptions=False).get(
        "/api/runs/analysis-test"
    )

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "an unexpected error occurred",
    }


def test_missing_run_preserves_typed_not_found_response() -> None:
    class MissingCatalog(StubCatalog):
        def open(self, analysis_id: str) -> object:
            raise RunNotFoundError(analysis_id)

    from grid_agent.trajectory.api.app import create_trajectory_app

    app = create_trajectory_app(
        cast(TrajectoryRunCatalog, MissingCatalog()), cast(object, SimpleNamespace())
    )
    response = TestClient(app).get("/api/runs/analysis-missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "run_not_found",
        "message": "trajectory run not found",
    }
