from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from grid_agent.trajectory.projection_models import (
    AgentStep,
    AgentTrajectory,
    AgentTurn,
    ArtifactIndex,
    ArtifactIndexRecord,
    ContextFrame,
    ContextTimeline,
    ModelRequest,
    ToolCall,
)

from .test_app import create_test_app


def _large_agent_turn() -> AgentTurn:
    request = ModelRequest(
        id="agent:analysis-test:request-large",
        source="observed",
        source_sequences=(3,),
        status="completed",
        request_id="request-large",
        tools=tuple(
            ToolCall(
                id=f"agent:analysis-test:tool-{sequence}",
                source="observed",
                source_sequences=(sequence,),
                status="completed",
                tool_call_id=f"tool-{sequence}",
                capability="gridctl",
                start_sequence=sequence,
                end_sequence=sequence,
                artifact_ref="/private/provider/tool-result.json",
                ok=True,
            )
            for sequence in range(4, 505)
        ),
    )
    return AgentTurn(
        id="agent:analysis-test:turn-large",
        source="observed",
        source_sequences=(1,),
        status="completed",
        turn_id="analysis-test-t-large",
        ordinal=1,
        steps=(
            AgentStep(
                id="agent:analysis-test:step-large",
                source="observed",
                source_sequences=(2,),
                status="completed",
                step_id="step-large",
                request=request,
            ),
        ),
    )


def test_agent_page_flattens_one_large_turn_and_binds_filters(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    catalog.projected = catalog.projected.model_copy(
        update={
            "source_fingerprint": "source-a",
            "agent": AgentTrajectory(
                analysis_id="analysis-test", turns=(_large_agent_turn(),)
            )
        }
    )
    client = TestClient(app)

    response = client.get(
        "/api/runs/analysis-test/agent",
        params={"kind": "tool", "capability": "gridctl"},
    )

    assert response.status_code == 200
    page = response.json()
    assert len(page["items"]) == 500
    assert page["has_older"] is True
    assert page["older_cursor"]
    assert page["encoded_bytes"] <= 2 * 1024 * 1024
    assert [row["source_sequence"] for row in page["items"]] == sorted(
        row["source_sequence"] for row in page["items"]
    )
    assert all(row["kind"] == "tool" for row in page["items"])
    assert all(row["parent_id"] == "agent:analysis-test:request-large" for row in page["items"])
    assert all(row["level"] == 4 for row in page["items"])
    assert all(row["title"] == "gridctl" for row in page["items"])
    assert "artifact_ref" not in page["items"][0]
    assert "/private/" not in response.text

    older = client.get(
        "/api/runs/analysis-test/agent",
        params={
            "kind": "tool",
            "capability": "gridctl",
            "cursor": page["older_cursor"],
        },
    )
    assert older.status_code == 200
    assert len(older.json()["items"]) == 1
    assert older.json()["items"][0]["source_sequence"] == 4

    foreign = client.get(
        "/api/runs/analysis-test/agent",
        params={"kind": "request", "cursor": page["older_cursor"]},
    )
    assert foreign.status_code == 400
    assert foreign.json()["code"] == "invalid_cursor"
    assert foreign.headers["content-security-policy"]

    catalog.projected = catalog.projected.model_copy(
        update={"source_fingerprint": "sha256:changed"}
    )
    stale = client.get(
        "/api/runs/analysis-test/agent",
        params={
            "kind": "tool",
            "capability": "gridctl",
            "cursor": page["older_cursor"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_cursor"


def test_agent_page_applies_turn_status_capability_and_text_filters(
    tmp_path: Path,
) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get(
        "/api/runs/analysis-test/agent",
        params={
            "turn_id": "analysis-test-t007",
            "kind": "tool",
            "status": "completed",
            "capability": "grid.analyze",
            "q": "GRID.ANALYZE",
        },
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["items"]] == [
        "agent:analysis-test:tool-7"
    ]


def test_agent_tool_row_preserves_recorded_completion_relation(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get(
        "/api/runs/analysis-test/agent",
        params={"kind": "tool", "q": "grid.analyze"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": "agent:analysis-test:tool-7",
            "parent_id": "agent:analysis-test:request-7",
            "turn_id": "analysis-test-t007",
            "kind": "tool",
            "level": 4,
            "source_sequence": 49,
            "start_sequence": 48,
            "end_sequence": 49,
            "related_refs": [],
            "source": "observed",
            "status": "completed",
            "unavailable_reason": None,
            "title": "Tool",
            "detail": None,
        }
    ]


def test_agent_page_never_echoes_internal_capabilities_or_artifact_paths(
    tmp_path: Path,
) -> None:
    app, _, _ = create_test_app(tmp_path)

    response = TestClient(app).get("/api/runs/analysis-test/agent")

    assert response.status_code == 200
    assert "provider_payload" not in response.text
    assert "artifact_ref" not in response.text
    assert "/private/" not in response.text


def test_context_page_is_summary_only_and_detail_remains_exact(tmp_path: Path) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/api/runs/analysis-test/context")

    assert response.status_code == 200
    page = response.json()
    assert page["items"] == [
        {
            "id": "context:analysis-test:900",
            "source_sequence": 900,
            "before_revision": 1,
            "after_revision": 2,
            "changed": True,
            "request_input_available": False,
            "request_input_unavailable_reason": "No following model request",
            "event_kind": "context-frame",
        }
    ]
    assert "before_state" not in response.text
    assert "after_state" not in response.text
    assert "request_artifact_ref" not in response.text

    detail = client.get("/api/runs/analysis-test/context", params={"at_sequence": 900})
    assert detail.status_code == 200
    assert detail.json()["before_state"] == {"model": "before"}
    assert detail.json()["delta"] == {"model": "changed"}
    assert detail.json()["after_state"] == {"model": "after"}
    assert detail.json()["max_sequence"] == 900


def test_context_filters_ranges_change_and_request_input(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    with_request = ContextFrame(
        id="context:analysis-test:901",
        source_sequences=(901,),
        rule_id="context-state-delta/v1",
        source_sequence=901,
        before_revision=2,
        after_revision=2,
        before_state_hash="b" * 64,
        after_state_hash="b" * 64,
        before_state={"model": "after"},
        delta={},
        after_state={"model": "after"},
        request_artifact_ref=catalog.artifact_ref,
    )
    catalog.projected = catalog.projected.model_copy(
        update={
            "context": ContextTimeline(
                analysis_id="analysis-test",
                frames=(*catalog.projected.context.frames, with_request),
            )
        }
    )
    client = TestClient(app)

    changed = client.get(
        "/api/runs/analysis-test/context",
        params={
            "from_sequence": 900,
            "to_sequence": 900,
            "from_revision": 1,
            "to_revision": 2,
            "changed": True,
            "request_input": False,
        },
    )
    unchanged = client.get(
        "/api/runs/analysis-test/context",
        params={"changed": False, "request_input": True},
    )

    assert changed.status_code == 200
    assert [row["source_sequence"] for row in changed.json()["items"]] == [900]
    assert unchanged.status_code == 200
    assert [row["source_sequence"] for row in unchanged.json()["items"]] == [901]


def test_context_request_input_requires_verified_artifact_registration(
    tmp_path: Path,
) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    request_ref = "artifact:unverified-request"
    persisted_reason = "request input digest did not match the registered artifact"
    frame = ContextFrame(
        id="context:analysis-test:901",
        source_sequences=(901,),
        rule_id="context-state-delta/v1",
        source_sequence=901,
        before_revision=2,
        after_revision=3,
        before_state_hash="b" * 64,
        after_state_hash="c" * 64,
        before_state={"model": "before"},
        delta={"model": "changed"},
        after_state={"model": "after"},
        request_artifact_ref=request_ref,
    )
    unverified = ArtifactIndexRecord(
        id="artifact:analysis-test:unverified-request",
        source="observed",
        source_sequences=(901,),
        status="unavailable",
        unavailable_reason=persisted_reason,
        reference=request_ref,
        kind="model-request",
        relative_path="unavailable",
        sha256="unavailable",
        verification_status="unavailable",
        producing_sequence=901,
    )
    catalog.projected = catalog.projected.model_copy(
        update={
            "context": ContextTimeline(
                analysis_id="analysis-test",
                frames=(frame,),
            ),
            "artifacts": ArtifactIndex(
                analysis_id="analysis-test",
                records={request_ref: unverified},
            ),
        }
    )
    client = TestClient(app)

    summary = client.get("/api/runs/analysis-test/context").json()["items"][0]
    detail = client.get(
        "/api/runs/analysis-test/context", params={"at_sequence": 901}
    ).json()

    assert summary["request_input_available"] is False
    assert summary["request_input_unavailable_reason"] == persisted_reason
    assert detail["request_input_available"] is False
    assert detail["request_input_unavailable_reason"] == persisted_reason
    assert detail["request_artifact_ref"] is None
    assert detail["unavailable_reason"] == persisted_reason


def test_evidence_page_maps_public_metadata_without_content(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    response = TestClient(app).get("/api/runs/analysis-test/evidence")

    assert response.status_code == 200
    page = response.json()
    assert "records" not in page
    assert len(page["items"]) == 1
    assert page["first_sequence"] == 900
    assert page["last_sequence"] == 900
    record = page["items"][0]
    assert record["reference"] == catalog.artifact_ref
    assert record["relative_path"] == "turns/answer.md"
    assert record["verification_status"] == "verified"
    assert "content" not in record
    assert "bytes" not in record
    assert "# Answer" not in response.text


def test_evidence_page_downgrades_unsafe_relative_paths_before_filtering(
    tmp_path: Path,
) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    unsafe = ArtifactIndexRecord(
        id="artifact:analysis-test:unsafe-path",
        source_sequences=(901,),
        reference="artifact:unsafe-path",
        kind="answer",
        relative_path="../outside.json",
        sha256="c" * 64,
        verification_status="verified",
    )
    catalog.projected = catalog.projected.model_copy(
        update={
            "artifacts": ArtifactIndex(
                analysis_id="analysis-test", records={unsafe.reference: unsafe}
            )
        }
    )
    client = TestClient(app)

    response = client.get("/api/runs/analysis-test/evidence")

    assert response.status_code == 200
    assert "../outside.json" not in response.text
    assert response.json()["items"] == [
        unsafe.model_dump(mode="json")
        | {
            "status": "unavailable",
            "unavailable_reason": "artifact path is unsafe for public display",
            "relative_path": "unavailable",
            "sha256": "unavailable",
            "verification_status": "unavailable",
        }
    ]
    assert client.get(
        "/api/runs/analysis-test/evidence",
        params={"verification_status": "verified"},
    ).json()["items"] == []
    unavailable = client.get(
        "/api/runs/analysis-test/evidence",
        params={"verification_status": "unavailable"},
    )
    assert [record["reference"] for record in unavailable.json()["items"]] == [
        unsafe.reference
    ]


def test_evidence_filters_lineage_sequence_and_sort(tmp_path: Path) -> None:
    app, catalog, _ = create_test_app(tmp_path)
    relevant = ArtifactIndexRecord(
        id="artifact:analysis-test:relevant",
        source="agent-declared",
        source_sequences=(40, 80),
        status="unavailable",
        unavailable_reason="artifact reference could not be verified",
        reference="evidence:relevant",
        kind="evidence",
        relative_path="unavailable",
        sha256="unavailable",
        verification_status="unavailable",
        producing_sequence=40,
        consuming_sequences=(80,),
        tool_call_id="tool-relevant",
        evidence_id="evidence:relevant",
    )
    records = dict(catalog.projected.artifacts.records)
    records[relevant.reference] = relevant
    catalog.projected = catalog.projected.model_copy(
        update={
            "artifacts": ArtifactIndex(analysis_id="analysis-test", records=records)
        }
    )
    client = TestClient(app)

    response = client.get(
        "/api/runs/analysis-test/evidence",
        params={
            "kind": "evidence",
            "source": "agent-declared",
            "verification_status": "unavailable",
            "from_sequence": 75,
            "to_sequence": 85,
            "relevant_ref": "tool-relevant",
            "sort": "verification_status",
        },
    )

    assert response.status_code == 200
    assert [row["reference"] for row in response.json()["items"]] == [
        "evidence:relevant"
    ]


def test_operational_pages_reject_unknown_invalid_and_ambiguous_queries(
    tmp_path: Path,
) -> None:
    app, _, _ = create_test_app(tmp_path)
    client = TestClient(app)

    for path in (
        "/api/runs/analysis-test/agent?kind=artifact",
        "/api/runs/analysis-test/agent?unknown=value",
        "/api/runs/analysis-test/context?from_sequence=10&to_sequence=1",
        "/api/runs/analysis-test/context?at_sequence=900&changed=true",
        "/api/runs/analysis-test/evidence?sort=path",
    ):
        response = client.get(path)
        assert response.status_code == 422
        assert response.json() == {
            "code": "invalid_request",
            "message": "request parameters are invalid",
        }
        assert response.headers["x-content-type-options"] == "nosniff"
