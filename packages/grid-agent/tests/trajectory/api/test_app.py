from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec, CursorState
from grid_agent.trajectory.api.models import RunSummary
from grid_agent.trajectory.projection_models import (
    AgentStep,
    AgentTrajectory,
    AgentTurn,
    ArtifactIndex,
    ArtifactIndexRecord,
    BusinessProblem,
    BusinessTrajectory,
    ContextFrame,
    ContextTimeline,
    ModelRequest,
    ProjectedRun,
    ToolCall,
)


MARKDOWN_REF = "artifact:sha256:" + "a" * 64


class StubCatalog:
    def __init__(self, tmp_path: Path) -> None:
        self.runs_root = tmp_path / "runs"
        self.run_root = self.runs_root / "analysis-test"
        artifact_path = self.run_root / "turns" / "answer.md"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text("# Answer\n", encoding="utf-8")
        content = artifact_path.read_bytes()
        artifact_ref = "artifact:sha256:" + sha256(content).hexdigest()
        artifact = ArtifactIndexRecord(
            id="artifact:analysis-test:answer",
            source_sequences=(900,),
            reference=artifact_ref,
            kind="answer",
            relative_path="turns/answer.md",
            sha256=sha256(content).hexdigest(),
            verification_status="verified",
        )
        problem = BusinessProblem(
            id="business:analysis-test:turn-1",
            source="derived",
            source_sequences=(900,),
            rule_id="problem-grouping/v1",
            status="completed",
            turn_id="analysis-test-t001",
            title="analysis-test-t001",
        )
        turn = AgentTurn(
            id="agent:analysis-test:turn-1",
            source="observed",
            source_sequences=(900,),
            status="completed",
            turn_id="analysis-test-t001",
            ordinal=1,
        )
        execution_turn = AgentTurn(
            id="agent:analysis-test:turn-7",
            source="observed",
            source_sequences=(45,),
            status="completed",
            turn_id="analysis-test-t007",
            ordinal=7,
            steps=(
                AgentStep(
                    id="agent:analysis-test:step-7",
                    source="observed",
                    source_sequences=(46,),
                    status="completed",
                    step_id="step-7",
                    request=ModelRequest(
                        id="agent:analysis-test:request-7",
                        source="observed",
                        source_sequences=(47,),
                        status="completed",
                        request_id="request-7",
                        artifact_ref="artifact:sha256:" + "b" * 64,
                        tools=(
                            ToolCall(
                                id="agent:analysis-test:tool-7",
                                source="observed",
                                source_sequences=(48, 49),
                                status="completed",
                                tool_call_id="tool-7",
                                capability="grid.analyze",
                                start_sequence=48,
                                end_sequence=49,
                                ok=True,
                            ),
                            ToolCall(
                                id="agent:analysis-test:unrelated-tool",
                                source="observed",
                                source_sequences=(50, 51),
                                status="completed",
                                tool_call_id="unrelated-tool",
                                capability="provider_payload.unrelated",
                                start_sequence=50,
                                end_sequence=51,
                                artifact_ref="/private/turns/provider_payload.json",
                                ok=True,
                            ),
                            ToolCall(
                                id="agent:analysis-test:48",
                                source="observed",
                                source_sequences=(56, 57),
                                status="completed",
                                tool_call_id="48",
                                capability="provider_payload.numeric-id",
                                start_sequence=56,
                                end_sequence=57,
                                artifact_ref="/private/turns/provider_payload.json",
                                ok=True,
                            ),
                        ),
                    ),
                ),
                AgentStep(
                    id="agent:analysis-test:unrelated-step",
                    source="observed",
                    source_sequences=(52,),
                    status="completed",
                    step_id="unrelated-step",
                    request=ModelRequest(
                        id="agent:analysis-test:unrelated-request",
                        source="observed",
                        source_sequences=(53,),
                        status="completed",
                        request_id="unrelated-request",
                        artifact_ref="/private/turns/provider_payload.json",
                        tools=(
                            ToolCall(
                                id="agent:analysis-test:unrelated-step-tool",
                                source="observed",
                                source_sequences=(54, 55),
                                status="completed",
                                tool_call_id="unrelated-step-tool",
                                capability="provider_payload.step",
                                start_sequence=54,
                                end_sequence=55,
                                artifact_ref="/private/turns/provider_payload.json",
                                ok=True,
                            ),
                        ),
                    ),
                ),
            ),
        )
        frame = ContextFrame(
            id="context:analysis-test:900",
            source_sequences=(900,),
            rule_id="context-state-delta/v1",
            source_sequence=900,
            before_revision=1,
            after_revision=2,
            before_state_hash="a" * 64,
            after_state_hash="b" * 64,
            before_state={"model": "before"},
            delta={"model": "changed"},
            after_state={"model": "after"},
            unavailable_reason="No following model request",
        )
        self.projected = ProjectedRun(
            analysis_id="analysis-test",
            source_fingerprint="sha256:source",
            agent=AgentTrajectory(analysis_id="analysis-test", turns=(execution_turn, turn)),
            business=BusinessTrajectory(analysis_id="analysis-test", problems=(problem,)),
            context=ContextTimeline(analysis_id="analysis-test", frames=(frame,)),
            artifacts=ArtifactIndex(analysis_id="analysis-test", records={artifact_ref: artifact}),
        )
        self.artifact_ref = artifact_ref

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

    def open(self, analysis_id: str) -> ProjectedRun:
        if analysis_id != "analysis-test":
            raise RunNotFoundError(analysis_id)
        return self.projected


def write_static_fixture(tmp_path: Path) -> Path:
    static_root = tmp_path / "static"
    assets = static_root / "assets"
    assets.mkdir(parents=True)
    (static_root / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div>'
        '<script type="module" src="/assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('workbench');", encoding="utf-8")
    (assets / "app.css").write_text("body { color: black; }", encoding="utf-8")
    return static_root


def create_test_app(
    tmp_path: Path, *, static_root: Path | None = None
) -> tuple[FastAPI, StubCatalog, CursorCodec]:
    from grid_agent.trajectory.api.app import create_trajectory_app

    catalog = StubCatalog(tmp_path)
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")
    return (
        create_trajectory_app(
            cast(TrajectoryRunCatalog, catalog),
            codec,
            static_root=static_root or write_static_fixture(tmp_path),
        ),
        catalog,
        codec,
    )


def test_spa_is_served_with_self_only_csp(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert '<script type="module" src="/assets/app.js"></script>' in response.text


def test_non_api_client_routes_fall_back_to_the_spa(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/runs/analysis-test/business")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_api_404_never_falls_back_to_spa(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/not-a-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_server_rejects_missing_production_assets(tmp_path: Path) -> None:
    from grid_agent.trajectory.api.app import create_trajectory_app

    catalog = StubCatalog(tmp_path)
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")

    with pytest.raises(RuntimeError, match="make build-workbench"):
        create_trajectory_app(
            cast(TrajectoryRunCatalog, catalog), codec, static_root=tmp_path / "missing"
        )


def test_api_lists_runs_with_a_typed_response(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs")

    assert response.status_code == 200
    assert response.json()["items"][0]["analysis_id"] == "analysis-test"


def test_api_run_detail_is_limited_to_catalog_metadata(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test")

    assert response.status_code == 200
    assert response.json() == {
        "analysis_id": "analysis-test",
        "status": "completed",
        "source_kind": "native",
        "started_at": "2026-08-14T08:18:22Z",
        "turn_count": 1,
        "last_sequence": 900,
        "replay_trusted_through": 900,
        "diagnostic": None,
    }
    assert "agent" not in response.json()
    assert "business" not in response.json()
    assert "context" not in response.json()
    assert "artifacts" not in response.json()


def test_api_pages_fixed_business_and_agent_views_with_signed_cursor(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    business = client.get("/api/runs/analysis-test/business")
    agent = client.get("/api/runs/analysis-test/agent")

    assert business.status_code == 200
    assert business.json()["items"][-1]["source_sequence"] == 900
    assert business.json()["older_cursor"] is None
    assert agent.status_code == 200
    assert agent.json()["items"][-1]["source_sequence"] == 900


def test_api_rejects_tampered_cursor_and_reports_stale_cursor(tmp_path: Path) -> None:
    app, catalog, codec = create_test_app(tmp_path)
    client = TestClient(app)

    assert client.get("/api/runs/analysis-test/business?cursor=invalid").json()["code"] == "invalid_cursor"
    cursor = codec.encode(
        CursorState(
            analysis_id="analysis-test",
            view="business",
            source_fingerprint="sha256:source",
            projection_version="business-trajectory/1.0",
            before_sequence=900,
        )
    )
    stale = catalog.projected.model_copy(update={"source_fingerprint": "sha256:changed"})
    catalog.projected = stale
    response = client.get(f"/api/runs/analysis-test/business?cursor={cursor}")
    assert response.status_code == 409
    assert response.json()["code"] == "stale_cursor"


def test_api_returns_context_frame_and_non_executable_artifact(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    client = TestClient(app)

    context = client.get("/api/runs/analysis-test/context?at_sequence=900")
    artifact = client.get(f"/api/runs/analysis-test/artifacts/{catalog.artifact_ref}")

    assert context.status_code == 200
    assert context.json()["source_sequence"] == 900
    assert context.json()["max_sequence"] == 900
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("text/markdown")
    assert "text/html" not in artifact.headers["content-type"]


def test_api_returns_only_the_typed_artifact_projection_for_evidence(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test/evidence")

    assert response.status_code == 200
    assert response.json() == catalog.projected.artifacts.model_dump(mode="json")


def test_execution_slice_returns_only_agent_records_causally_bound_to_sequence(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/api/runs/analysis-test/execution?at_sequence=48")

    assert response.status_code == 200
    assert response.json()["turn"]["turn_id"] == "analysis-test-t007"
    assert response.json()["turn"]["steps"][0]["step_id"] == "step-7"
    assert response.json()["turn"]["steps"][0]["request"]["tools"][0]["tool_call_id"] == "tool-7"
    assert len(response.json()["turn"]["steps"]) == 1
    assert len(response.json()["turn"]["steps"][0]["request"]["tools"]) == 1
    assert response.json()["source_sequence"] == 48
    assert response.json()["unavailable_reason"] is None
    assert "provider_payload" not in response.text
    assert "/turns/" not in response.text


def test_execution_slice_is_explicitly_unavailable_without_durable_linkage(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test/execution?at_sequence=777")

    assert response.status_code == 200
    assert response.json()["turn"] is None
    assert response.json()["source_sequence"] == 777
    assert response.json()["unavailable_reason"] == "no durable execution linkage is recorded"


def test_api_has_no_mutation_routes(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/runs/analysis-test").status_code == 405
        assert method("/api/runs/analysis-test/execution?at_sequence=48").status_code == 405


def test_every_response_has_browser_security_headers_without_cors(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    response = TestClient(app).get("/api/runs")

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


def test_request_validation_errors_are_typed_and_secured(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test/context?at_sequence=zero")

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_request",
        "message": "request parameters are invalid",
    }
    assert response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_openapi_exposes_only_get_methods(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    methods = {method for path in app.openapi()["paths"].values() for method in path}

    assert methods == {"get"}


def test_missing_run_preserves_typed_not_found_response(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    response = TestClient(app).get("/api/runs/analysis-missing")

    assert response.status_code == 404
    assert response.json() == {
        "code": "run_not_found",
        "message": "trajectory run not found",
    }
