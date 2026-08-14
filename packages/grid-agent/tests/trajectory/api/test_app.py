from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec, CursorState
from grid_agent.trajectory.api.models import RunSummary
from grid_agent.trajectory.projection_models import (
    AgentTrajectory,
    AgentTurn,
    ArtifactIndex,
    ArtifactIndexRecord,
    BusinessProblem,
    BusinessTrajectory,
    ContextFrame,
    ContextTimeline,
    ProjectedRun,
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
            agent=AgentTrajectory(analysis_id="analysis-test", turns=(turn,)),
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


def create_test_app(tmp_path: Path) -> tuple[FastAPI, StubCatalog, CursorCodec]:
    from grid_agent.trajectory.api.app import create_trajectory_app

    catalog = StubCatalog(tmp_path)
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")
    return create_trajectory_app(cast(TrajectoryRunCatalog, catalog), codec), catalog, codec


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


def test_api_has_no_mutation_routes(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/runs/analysis-test").status_code == 405


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
