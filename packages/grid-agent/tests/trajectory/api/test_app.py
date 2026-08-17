from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec, CursorState
from grid_agent.trajectory.api.models import RunSummary
from grid_agent.analysis.integrity import _sha256_canonical_json
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.events import EventDraft, EventRefs, EventSource, RunScope
from grid_agent.trajectory.projection_models import (
    AgentStep,
    AgentTrajectory,
    AgentTurn,
    ArtifactIndex,
    ArtifactIndexRecord,
    BusinessNode,
    BusinessProblem,
    BusinessTrajectory,
    ContextFrame,
    ContextTimeline,
    ModelRequest,
    ProjectedRun,
    ToolCall,
)
from grid_agent.trajectory.recorder import RunEventRecorder
from grid_agent.trajectory.service import ProjectionService


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
            nodes=(
                BusinessNode(
                    id="business:analysis-test:900:decision",
                    source="agent-declared",
                    source_sequences=(900,),
                    status="completed",
                    kind="decision",
                    title="Recorded decision",
                ),
            ),
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


def _sha256_canonical_sorted(value: object) -> str:
    encoded = json.dumps(
        _sort_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _sort_json(value: object) -> object:
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    return value


def _canonical_request_document() -> dict[str, Any]:
    semantic_request: dict[str, Any] = {
        "model": {
            "provider": "openai",
            "api": "openai-responses",
            "id": "gpt-5.5",
        },
        "context": {
            "system_prompt": "final system prompt",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "question"}],
                }
            ],
            "tools": [
                {
                    "name": "grid_context_open",
                    "description": "Open a grid context.",
                    "parameters": {"type": "object", "additionalProperties": False},
                }
            ],
        },
        "options": {"transport": "sse", "temperature": 0},
    }
    return {
        "schema_version": "grid-model-request-input/2.0",
        "request_id": "analysis-native-artifacts-t001-r001",
        "request_index": 1,
        "turn_id": "analysis-native-artifacts-t001",
        "captured_at": "2026-08-17T00:00:00Z",
        "source_event_sequences": [3],
        "context_revision": 1,
        "context_state_hash": "1" * 64,
        "runtime": {
            "pi_coding_agent_version": "0.80.6",
            "pi_ai_version": "0.80.6",
            "pi_source_commit": "1" * 40,
            "pi_patch_set_sha256": "2" * 64,
        },
        "semantic_request": semantic_request,
        "semantic_request_sha256": _sha256_canonical_sorted(semantic_request),
    }


def write_native_run_with_simulator_artifacts(runs_root: Path) -> tuple[Path, dict[str, str]]:
    run_root = runs_root / "analysis-native-artifacts"
    run_root.mkdir(parents=True)
    registry = ImmutableArtifactRegistry(run_root)
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-native-artifacts",
        artifact_registry=registry,
    )
    scope = RunScope(
        turn_id="analysis-native-artifacts-t001",
        step_id="analysis-native-artifacts-t001-s001",
        request_id="analysis-native-artifacts-t001-r001",
        tool_call_id="call-1",
    )
    request = registry.write_json(
        "request-input",
        "analysis-native-artifacts-t001-r001",
        _canonical_request_document(),
    )
    response = registry.write_json(
        "model-response",
        "analysis-native-artifacts-t001-r001",
        {"schema_version": "grid-model-response/1.0", "message": {"role": "assistant"}},
    )
    answer = registry.write_json(
        "answer",
        "answer-1",
        {"schema_version": "grid-answer/1.0", "answer_output": "verified"},
    )
    context = registry.write_json(
        "context-view",
        "revision-1",
        {
            "analysis_id": "analysis-native-artifacts",
            "revision": 1,
            "state_hash": "sha256:" + "1" * 64,
        },
    )
    tool = registry.write_json(
        "tool-result",
        "analysis-native-artifacts-t001:call-1",
        {
            "schema_version": "grid-tool-invocation/1.0",
            "turn_id": "analysis-native-artifacts-t001",
            "request_id": "analysis-native-artifacts-t001-r001",
            "tool_call_id": "call-1",
            "tool_name": "grid_analysis_powerflow_ac",
            "arguments": {},
        },
    )

    evidence_document = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "context_ref": "context:sha256:" + "2" * 64,
        "revision_ref": "revision:sha256:" + "3" * 64,
    }
    evidence_digest = _sha256_canonical_json(evidence_document)
    evidence_ref = f"evidence:sha256:{evidence_digest}"
    evidence_path = run_root / "evidence/network-facts" / f"network-fact-{evidence_digest}.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps(evidence_document, separators=(",", ":")) + "\n", encoding="utf-8")
    registry.register_existing("evidence", evidence_ref, evidence_path)

    result_body = {
        "schema_version": "grid-result/1.0",
        "result_type": "powerflow",
        "context_ref": "context:sha256:" + "2" * 64,
        "revision_ref": "revision:sha256:" + "3" * 64,
        "evidence_refs": [evidence_ref],
        "payload": {"converged": True},
    }
    result_digest = _sha256_canonical_json(result_body)
    result_ref = f"result:sha256:{result_digest}"
    result_path = run_root / "evidence/results" / f"powerflow-{result_digest}.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps({**result_body, "result_ref": result_ref}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    registry.register_existing("result", result_ref, result_path)

    recorder.append(EventDraft(event_type="analysis.started", payload={}))
    recorder.append(
        EventDraft(
            event_type="turn.started",
            scope=RunScope(turn_id="analysis-native-artifacts-t001"),
            payload={"ordinal": 1, "instruction_sha256": "4" * 64},
        )
    )
    recorder.append(
        EventDraft(
            event_type="context.injected",
            scope=scope,
            refs=EventRefs(produced=(context.ref,)),
            payload={"revision": 1, "state_hash": "sha256:" + "1" * 64, "artifact_ref": context.ref},
        )
    )
    recorder.append(
        EventDraft(
            event_type="model.request.started",
            scope=scope,
            refs=EventRefs(produced=(request.ref,)),
            payload={"artifact_ref": request.ref, "request_index": 1},
        )
    )
    recorder.append(
        EventDraft(
            event_type="tool.started",
            scope=scope,
            refs=EventRefs(produced=(tool.ref,)),
            payload={"capability": "analysis.powerflow.ac.run", "artifact_ref": tool.ref},
        )
    )
    recorder.append(
        EventDraft(
            event_type="tool.completed",
            scope=scope,
            refs=EventRefs(consumed=(tool.ref,), produced=(result_ref,), evidence=(evidence_ref,)),
            payload={"capability": "analysis.powerflow.ac.run", "artifact_ref": tool.ref, "ok": True},
        )
    )
    recorder.append(
        EventDraft(
            event_type="model.response.completed",
            scope=scope,
            refs=EventRefs(produced=(response.ref,)),
            payload={"artifact_ref": response.ref, "stop_reason": "stop"},
        )
    )
    recorder.append(
        EventDraft(
            event_type="answer.submitted",
            scope=RunScope(turn_id="analysis-native-artifacts-t001"),
            refs=EventRefs(produced=(answer.ref,), consumed=(result_ref,), evidence=(evidence_ref,)),
            payload={"submission_id": "answer-1", "artifact_ref": answer.ref, "result_refs": (result_ref,), "evidence_refs": (evidence_ref,)},
        )
    )
    recorder.append(
        EventDraft(
            event_type="business.claim.declared",
            scope=scope,
            source=EventSource(kind="agent-declared", producer="test"),
            refs=EventRefs(consumed=(result_ref,), evidence=(evidence_ref,)),
            payload={
                "submission_id": "answer-1",
                "statement": "The power flow result is verified.",
                "category": "numerical_result",
                "result_refs": (result_ref,),
                "evidence_refs": (evidence_ref,),
            },
        )
    )
    recorder.append(
        EventDraft(
            event_type="business.claim.declared",
            scope=scope,
            source=EventSource(kind="agent-declared", producer="test"),
            refs=EventRefs(consumed=("result:sha256:" + "f" * 64,)),
            payload={
                "submission_id": "answer-1",
                "statement": "This missing result remains unavailable.",
                "category": "numerical_result",
                "result_refs": ("result:sha256:" + "f" * 64,),
                "evidence_refs": (),
            },
        )
    )
    recorder.append(
        EventDraft(
            event_type="analysis.completed",
            payload={"completed_turns": 1, "total_turns": 1},
        )
    )
    recorder.close()
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "grid-agent-analysis-manifest/1.0",
                "analysis_id": "analysis-native-artifacts",
                "status": "completed",
                "completed_turns": 1,
                "total_turns": 1,
                "events_path": "events/run-events.jsonl",
                "trajectory_schema_version": "grid-run-event/1.0",
            }
        ),
        encoding="utf-8",
    )
    return run_root, {
        "request_ref": request.ref,
        "response_ref": response.ref,
        "answer_ref": answer.ref,
        "context_ref": context.ref,
        "tool_ref": tool.ref,
        "result_ref": result_ref,
        "evidence_ref": evidence_ref,
        "missing_ref": "result:sha256:" + "f" * 64,
    }


def create_native_catalog_app(tmp_path: Path) -> tuple[FastAPI, dict[str, str]]:
    runs_root = tmp_path / "runs"
    _run_root, refs = write_native_run_with_simulator_artifacts(runs_root)
    cache_root = tmp_path / ".grid-agent/trajectory-cache"
    catalog = TrajectoryRunCatalog(runs_root, cache_root, ProjectionService(cache_root))
    from grid_agent.trajectory.api.app import create_trajectory_app

    return create_trajectory_app(catalog, CursorCodec.load_or_create(cache_root / "cursor.key"), static_root=write_static_fixture(tmp_path)), refs


def write_native_run_with_historical_v1_request(runs_root: Path) -> tuple[Path, str]:
    run_root = runs_root / "analysis-historical-v1-request"
    run_root.mkdir(parents=True)
    registry = ImmutableArtifactRegistry(run_root)
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-historical-v1-request",
        artifact_registry=registry,
    )
    scope = RunScope(
        turn_id="analysis-historical-v1-request-t001",
        step_id="analysis-historical-v1-request-t001-s001",
        request_id="analysis-historical-v1-request-t001-r001",
    )
    request = registry.write_json(
        "request-input",
        "analysis-historical-v1-request-t001-r001",
        {
            "schema_version": "grid-model-request-input/1.0",
            "request_id": "analysis-historical-v1-request-t001-r001",
            "request_index": 1,
            "turn_id": "analysis-historical-v1-request-t001",
            "provider": "openai",
            "model": "legacy-model",
            "provider_payload": {
                "messages": [{"role": "user", "content": "legacy question"}],
                "tools": [],
            },
        },
    )
    recorder.append(EventDraft(event_type="analysis.started", payload={}))
    recorder.append(
        EventDraft(
            event_type="turn.started",
            scope=RunScope(turn_id="analysis-historical-v1-request-t001"),
            payload={"ordinal": 1, "instruction_sha256": "4" * 64},
        )
    )
    recorder.append(
        EventDraft(
            event_type="model.request.started",
            scope=scope,
            refs=EventRefs(produced=(request.ref,)),
            payload={"artifact_ref": request.ref, "request_index": 1},
        )
    )
    recorder.append(
        EventDraft(
            event_type="analysis.completed",
            payload={"completed_turns": 1, "total_turns": 1},
        )
    )
    recorder.close()
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "grid-agent-analysis-manifest/1.0",
                "analysis_id": "analysis-historical-v1-request",
                "status": "completed",
                "completed_turns": 1,
                "total_turns": 1,
                "events_path": "events/run-events.jsonl",
                "trajectory_schema_version": "grid-run-event/1.0",
            }
        ),
        encoding="utf-8",
    )
    return run_root, request.ref


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


def test_business_api_pages_causal_rows_inside_one_large_problem_with_exact_cursor(
    tmp_path: Path,
) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    nodes = tuple(
        BusinessNode(
            id=f"business:analysis-test:{sequence}:decision",
            source="agent-declared",
            source_sequences=(sequence,),
            status="completed",
            kind="decision",
            title=f"Decision {sequence}",
            detail="x" * 5_000,
        )
        for sequence in range(1, 1_002)
    )
    problem = BusinessProblem(
        id="business:analysis-test:large-turn",
        source="derived",
        source_sequences=tuple(range(1, 1_002)),
        rule_id="problem-grouping/v1",
        status="completed",
        turn_id="analysis-test-large-turn",
        title="One turn with more than two megabytes of causal nodes",
        nodes=nodes,
    )
    catalog.projected = catalog.projected.model_copy(
        update={
            "business": BusinessTrajectory(
                analysis_id="analysis-test", problems=(problem,)
            )
        }
    )
    client = TestClient(app)

    newest = client.get("/api/runs/analysis-test/business")

    assert newest.status_code == 200
    newest_page = newest.json()
    assert newest_page["analysis_id"] == "analysis-test"
    assert 0 < len(newest_page["items"]) <= 500
    assert newest_page["encoded_bytes"] <= 2 * 1024 * 1024
    assert newest_page["has_older"] is True
    assert newest_page["older_cursor"]
    assert all(len(row["nodes"]) == 1 for row in newest_page["items"])
    assert all("nodes" not in row["problem"] for row in newest_page["items"])
    assert all("source_sequences" not in row["problem"] for row in newest_page["items"])
    assert {
        row["problem"]["id"] for row in newest_page["items"]
    } == {"business:analysis-test:large-turn"}
    assert {
        row["problem"]["node_count"] for row in newest_page["items"]
    } == {1_001}
    assert newest_page["last_sequence"] == 1_001

    older = client.get(
        "/api/runs/analysis-test/business",
        params={"cursor": newest_page["older_cursor"]},
    )

    assert older.status_code == 200
    older_page = older.json()
    assert older_page["analysis_id"] == "analysis-test"
    assert older_page["last_sequence"] == newest_page["first_sequence"] - 1
    newest_sequences = {row["source_sequence"] for row in newest_page["items"]}
    older_sequences = {row["source_sequence"] for row in older_page["items"]}
    assert newest_sequences.isdisjoint(older_sequences)


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


def test_api_pages_only_typed_artifact_projection_records_for_evidence(
    tmp_path: Path,
) -> None:
    app, catalog, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test/evidence")

    assert response.status_code == 200
    page = response.json()
    assert page["analysis_id"] == catalog.projected.analysis_id
    assert page["items"] == [
        record.model_dump(mode="json")
        for record in catalog.projected.artifacts.records.values()
    ]
    assert page["has_older"] is False
    assert page["older_cursor"] is None


def test_native_api_verifies_simulator_artifacts_and_downloads_exact_bytes(tmp_path: Path) -> None:
    app, refs = create_native_catalog_app(tmp_path)
    client = TestClient(app)

    runs = client.get("/api/runs")
    business = client.get("/api/runs/analysis-native-artifacts/business")
    evidence = client.get("/api/runs/analysis-native-artifacts/evidence")

    assert runs.status_code == 200
    assert runs.json()["items"][0]["status"] == "completed"
    assert business.status_code == 200
    assert any(
        node["kind"] == "verified-result"
        for problem in business.json()["items"]
        for node in problem["nodes"]
    )
    assert evidence.status_code == 200
    records = {record["reference"]: record for record in evidence.json()["items"]}
    for reference, kind, path_prefix in (
        (refs["request_ref"], "request-input", "requests/"),
        (refs["response_ref"], "model-response", "requests/"),
        (refs["answer_ref"], "answer", "turns/"),
        (refs["context_ref"], "context-view", "context/views/"),
        (refs["tool_ref"], "tool-result", "tool-results/"),
        (refs["result_ref"], "result", "evidence/results/"),
        (refs["evidence_ref"], "evidence", "evidence/network-facts/"),
    ):
        record = records[reference]
        assert record["verification_status"] == "verified"
        assert record["kind"] == kind
        assert record["relative_path"].startswith(path_prefix)
        assert ".." not in Path(record["relative_path"]).parts
        artifact = client.get(f"/api/runs/analysis-native-artifacts/artifacts/{reference}")
        assert artifact.status_code == 200
        assert sha256(artifact.content).hexdigest() == record["sha256"]


def test_native_api_reads_historical_v1_request_without_mutating_bytes(
    tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    run_root, request_ref = write_native_run_with_historical_v1_request(runs_root)
    request_path = next((run_root / "requests").glob("*/input.json"))
    before = request_path.read_bytes()
    cache_root = tmp_path / ".grid-agent/trajectory-cache"
    catalog = TrajectoryRunCatalog(runs_root, cache_root, ProjectionService(cache_root))
    from grid_agent.trajectory.api.app import create_trajectory_app

    app = create_trajectory_app(
        catalog,
        CursorCodec.load_or_create(cache_root / "cursor.key"),
        static_root=write_static_fixture(tmp_path),
    )
    client = TestClient(app)

    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/runs/analysis-historical-v1-request/agent").status_code == 200
    evidence = client.get("/api/runs/analysis-historical-v1-request/evidence")
    artifact = client.get(
        f"/api/runs/analysis-historical-v1-request/artifacts/{request_ref}"
    )

    assert evidence.status_code == 200
    records = {record["reference"]: record for record in evidence.json()["items"]}
    assert records[request_ref]["verification_status"] == "verified"
    assert artifact.status_code == 200
    assert artifact.content == before
    assert request_path.read_bytes() == before
    assert json.loads(before)["schema_version"] == "grid-model-request-input/1.0"


def test_native_api_keeps_unsupported_refs_explicitly_unavailable(tmp_path: Path) -> None:
    app, refs = create_native_catalog_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-native-artifacts/evidence")

    assert response.status_code == 200
    records = {record["reference"]: record for record in response.json()["items"]}
    record = records[refs["missing_ref"]]
    assert record["verification_status"] == "unavailable"
    assert record["status"] == "unavailable"
    assert record["relative_path"] == "unavailable"


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
    assert "reasoning_content" not in response.text
    assert "thinkingSignature" not in response.text
    assert "GRID_AGENT_TRAJECTORY_ACKS" not in response.text
    assert "/turns/" not in response.text


def test_execution_slice_resolves_a_claim_only_through_verified_artifact_lineage(
    tmp_path: Path,
) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    reference = "evidence:sha256:" + "c" * 64
    claim = BusinessNode(
        id="business:analysis-test:60:claim",
        source="agent-declared",
        source_sequences=(60,),
        status="completed",
        kind="claim",
        title="Claim linked only through evidence",
        refs=(reference,),
    )
    problem = BusinessProblem(
        id="business:analysis-test:turn-7",
        source="derived",
        source_sequences=(60,),
        rule_id="problem-grouping/v1",
        status="completed",
        turn_id="analysis-test-t007",
        title="analysis-test-t007",
        nodes=(claim,),
    )
    lineage = ArtifactIndexRecord(
        id="artifact:analysis-test:lineage",
        source_sequences=(49, 60),
        reference=reference,
        kind="evidence",
        relative_path="evidence/lineage.json",
        sha256="c" * 64,
        verification_status="verified",
        producing_sequence=49,
        consuming_sequences=(60,),
        turn_id="analysis-test-t007",
        step_id="step-7",
        request_id="request-7",
        tool_call_id="tool-7",
        result_id="result-7",
        evidence_id=reference,
        claim_id=claim.id,
    )
    catalog.projected = catalog.projected.model_copy(
        update={
            "business": BusinessTrajectory(
                analysis_id="analysis-test", problems=(problem,)
            ),
            "artifacts": ArtifactIndex(
                analysis_id="analysis-test", records={reference: lineage}
            ),
        }
    )

    response = TestClient(app).get(
        "/api/runs/analysis-test/execution?at_sequence=60"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["turn"]["turn_id"] == "analysis-test-t007"
    assert body["turn"]["steps"][0]["step_id"] == "step-7"
    assert body["turn"]["steps"][0]["request"]["request_id"] == "request-7"
    assert [
        tool["tool_call_id"]
        for tool in body["turn"]["steps"][0]["request"]["tools"]
    ] == ["tool-7"]
    assert body["lineage"]["business_node_ids"] == [claim.id]
    assert body["lineage"]["artifact_refs"] == [reference]
    assert body["lineage"]["request_ids"] == ["request-7"]
    assert body["lineage"]["tool_call_ids"] == ["tool-7"]
    assert body["lineage"]["result_ids"] == ["result-7"]
    assert "unrelated" not in response.text
    assert "numeric-id" not in response.text
    assert "provider_payload" not in response.text
    assert "reasoning_content" not in response.text
    assert "thinkingSignature" not in response.text
    assert "GRID_AGENT_TRAJECTORY_ACKS" not in response.text


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
