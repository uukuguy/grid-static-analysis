from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from grid_agent.analysis.integrity import _sha256_canonical_json
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.capture import CaptureIntegrityError, NativeCaptureAdapter
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RunEventRecorder


class Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        value = self.value
        self.value += 0.25
        return value


def native_capture_fixture(
    tmp_path: Path,
) -> tuple[RunEventRecorder, NativeCaptureAdapter, AnalysisWorkspace]:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    adapter = NativeCaptureAdapter(recorder, artifacts, workspace, clock=Clock())
    return recorder, adapter, workspace


def write_request_input(
    workspace: AnalysisWorkspace,
    *,
    request_id: str,
    index: int,
    source_event_sequences: list[int] | None = None,
    semantic_request: dict[str, Any] | None = None,
    semantic_request_sha256: str | None = None,
) -> Path:
    semantic = semantic_request or semantic_request_fixture()
    path = workspace.requests_path / request_id / "input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "grid-model-request-input/2.0",
                "request_id": request_id,
                "request_index": index,
                "turn_id": "analysis-test-t001",
                "captured_at": "2026-08-14T00:00:00.000Z",
                "source_event_sequences": source_event_sequences or [7],
                "context_revision": 1,
                "context_state_hash": "a" * 64,
                "runtime": {
                    "pi_coding_agent_version": "0.80.6",
                    "pi_ai_version": "0.80.6",
                    "pi_source_commit": "1" * 40,
                    "pi_patch_set_sha256": "2" * 64,
                },
                "semantic_request": semantic,
                "semantic_request_sha256": semantic_request_sha256
                or sha256_canonical_sorted(semantic),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def capture_with_active_request(
    tmp_path: Path,
) -> tuple[RunEventRecorder, NativeCaptureAdapter, AnalysisWorkspace]:
    recorder, adapter, workspace = native_capture_fixture(tmp_path)
    adapter.begin_turn("analysis-test-t001")
    write_request_input(
        workspace,
        request_id="analysis-test-t001-r001",
        index=1,
    )
    adapter.drain_model_requests()
    return recorder, adapter, workspace


def semantic_request_fixture(
    *,
    provider: str = "scripted",
    model_id: str = "scripted-model",
) -> dict[str, Any]:
    return {
        "model": {
            "provider": provider,
            "api": "openai-responses",
            "id": model_id,
        },
        "context": {
            "system_prompt": "system",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "question"}],
                }
            ],
            "tools": [
                {
                    "name": "grid_context_open",
                    "description": "Open context.",
                    "parameters": {"type": "object", "additionalProperties": False},
                }
            ],
        },
        "options": {
            "reasoning": "medium",
            "thinkingBudgets": {"medium": 1024},
            "temperature": 0,
            "maxTokens": 1024,
            "transport": "sse",
            "cacheRetention": "short",
            "timeoutMs": 1000,
            "websocketConnectTimeoutMs": 1000,
            "maxRetries": 1,
            "maxRetryDelayMs": 100,
        },
    }


def sha256_canonical_sorted(value: object) -> str:
    import hashlib

    encoded = json.dumps(
        _sort_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sort_json(value: object) -> object:
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    return value


def events(recorder: RunEventRecorder):  # type: ignore[no-untyped-def]
    return RunEventReader(recorder.events_path).read_prefix().events


def acknowledgement_path(workspace: AnalysisWorkspace, request_id: str) -> Path:
    return (
        workspace.root_path.parent.parent
        / ".grid-agent"
        / "trajectory-acks"
        / workspace.analysis_id
        / f"{request_id}.committed.json"
    )


def acknowledgement(workspace: AnalysisWorkspace, request_id: str) -> dict[str, Any]:
    return json.loads(acknowledgement_path(workspace, request_id).read_text(encoding="utf-8"))


def test_model_request_commit_ack_uses_verified_declared_digest_after_event_append(
    tmp_path: Path,
) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    request_id = "analysis-test-t001-r001"
    observed_ack_visibility: list[bool] = []

    def observe_started_event(event: object) -> None:
        if getattr(event, "event_type", None) == "model.request.started":
            observed_ack_visibility.append(acknowledgement_path(workspace, request_id).exists())

    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
        subscribers=(observe_started_event,),
    )
    adapter = NativeCaptureAdapter(recorder, artifacts, workspace, clock=Clock())
    semantic = semantic_request_fixture(provider="deepseek", model_id="deepseek-v4")
    adapter.begin_turn("analysis-test-t001")
    write_request_input(
        workspace,
        request_id=request_id,
        index=1,
        source_event_sequences=[11, 13],
        semantic_request=semantic,
    )

    adapter.drain_model_requests()
    adapter.drain_model_requests()

    recorded = events(recorder)
    ack = acknowledgement(workspace, request_id)
    expected_digest = sha256_canonical_sorted(semantic)
    assert [event.event_type for event in recorded] == ["model.request.started"]
    assert observed_ack_visibility == [False]
    assert ack == {
        "schema_version": "grid-model-request-commit/1.0",
        "request_id": request_id,
        "semantic_request_sha256": expected_digest,
        "artifact_ref": recorded[0].payload["artifact_ref"],
        "event_sequence": recorded[0].sequence,
        "status": "committed",
    }
    assert recorded[0].causation.parent_sequence == 13

    adapter.on_raw_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
            },
        }
    )
    response = json.loads(
        (workspace.requests_path / request_id / "response.json").read_text(
            encoding="utf-8"
        )
    )
    assert response["provider"] == "deepseek"
    assert response["model"] == "deepseek-v4"


def test_model_request_digest_mismatch_does_not_ack_or_advance_state(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = native_capture_fixture(tmp_path)
    request_id = "analysis-test-t001-r001"
    adapter.begin_turn("analysis-test-t001")
    write_request_input(
        workspace,
        request_id=request_id,
        index=1,
        semantic_request_sha256="f" * 64,
    )

    with pytest.raises(CaptureIntegrityError, match="semantic_request_sha256"):
        adapter.drain_model_requests()

    assert not acknowledgement_path(workspace, request_id).exists()
    assert events(recorder) == ()


def test_malformed_model_request_does_not_ack_or_advance_state(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = native_capture_fixture(tmp_path)
    request_id = "analysis-test-t001-r001"
    adapter.begin_turn("analysis-test-t001")
    request_path = write_request_input(workspace, request_id=request_id, index=1)
    malformed = json.loads(request_path.read_text(encoding="utf-8"))
    malformed["runtime"].pop("pi_source_commit")
    request_path.write_text(
        json.dumps(malformed, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CaptureIntegrityError, match="runtime"):
        adapter.drain_model_requests()

    assert not acknowledgement_path(workspace, request_id).exists()
    assert events(recorder) == ()

    write_request_input(workspace, request_id=request_id, index=1)
    adapter.drain_model_requests()

    assert acknowledgement_path(workspace, request_id).is_file()
    assert [event.event_type for event in events(recorder)] == ["model.request.started"]


def test_capture_orders_request_response_and_tool_events(tmp_path: Path) -> None:
    recorder, adapter, workspace = native_capture_fixture(tmp_path)
    adapter.begin_turn("analysis-test-t001")
    request_path = write_request_input(
        workspace,
        request_id="analysis-test-t001-r001",
        index=1,
        source_event_sequences=[7, 9],
    )

    adapter.drain_model_requests()
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-1",
            "tool_name": "grid_context_open",
            "args": {},
        },
        10,
    )
    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-1",
            "capability": "context.open",
            "ok": True,
            "result": {},
            "evidence_refs": [],
        },
        11,
    )
    adapter.on_raw_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input": 10, "output": 3},
            },
        }
    )

    recorded = events(recorder)
    assert [event.event_type for event in recorded] == [
        "model.request.started",
        "tool.started",
        "tool.completed",
        "model.response.completed",
    ]
    assert recorded[0].causation.parent_sequence == 9
    assert recorded[0].refs.produced[0].startswith("artifact:sha256:")
    assert str(request_path) not in recorded[0].refs.produced
    assert recorded[1].scope.request_id == "analysis-test-t001-r001"
    assert recorded[2].scope.tool_call_id == "call-1"
    assert recorded[2].causation.parent_sequence == recorded[1].sequence
    assert recorded[3].payload["input_tokens"] == 10
    assert recorded[3].payload["output_tokens"] == 3
    assert recorded[3].refs.produced == (recorded[3].payload["artifact_ref"],)

    response_path = workspace.requests_path / "analysis-test-t001-r001" / "response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["message"] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "done"}],
    }
    assert response["usage"] == {"input": 10, "output": 3}


def test_capture_records_tool_use_after_its_completed_model_response(
    tmp_path: Path,
) -> None:
    recorder, adapter, _workspace = capture_with_active_request(tmp_path)

    adapter.on_raw_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "id": "call-1"}],
                "stopReason": "toolUse",
            },
        }
    )
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-1",
            "tool_name": "grid_model_list",
            "args": {},
        },
        20,
    )
    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-1",
            "capability": "model.list",
            "ok": True,
            "result": {},
            "evidence_refs": [],
        },
        21,
    )

    recorded = events(recorder)
    assert [event.event_type for event in recorded] == [
        "model.request.started",
        "model.response.completed",
        "tool.started",
        "tool.completed",
    ]
    assert recorded[2].scope.request_id == recorded[0].scope.request_id
    assert recorded[3].causation.parent_sequence == recorded[2].sequence


def test_stream_deltas_only_update_ttft_and_never_persist_hidden_reasoning(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = capture_with_active_request(tmp_path)

    adapter.on_raw_event({"type": "text_delta", "text": "first"})
    adapter.on_raw_event(
        {
            "type": "message_update",
            "assistantMessageEvent": {
                "type": "thinking_delta",
                "delta": "private reasoning",
            },
        }
    )
    assert events(recorder)[-1].event_type == "model.request.started"

    adapter.on_raw_event(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "private reasoning"},
                    {"type": "text", "text": "public"},
                ],
            },
        }
    )

    response = events(recorder)[-1]
    assert response.payload["ttft_seconds"] is not None
    assert response.payload["ttft_seconds"] >= 0
    response_document = json.loads(
        (
            workspace.requests_path
            / "analysis-test-t001-r001"
            / "response.json"
        ).read_text(encoding="utf-8")
    )
    assert response_document["message"]["content"] == [
        {"type": "text", "text": "public"}
    ]
    assert "private reasoning" not in json.dumps(response_document)


def test_capture_maps_prompt_provider_retry_and_interruption_events(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = capture_with_active_request(tmp_path)
    adapter.on_raw_event(
        {
            "type": "agent_end",
            "willRetry": True,
            "messages": [
                {
                    "role": "assistant",
                    "stopReason": "error",
                    "errorMessage": "provider unavailable",
                }
            ],
        }
    )
    adapter.on_raw_event(
        {
            "type": "auto_retry_start",
            "attempt": 1,
            "maxAttempts": 3,
            "delayMs": 500,
            "errorMessage": "provider unavailable",
        }
    )
    adapter.on_raw_event({"type": "auto_retry_end", "success": True, "attempt": 2})

    write_request_input(
        workspace,
        request_id="analysis-test-t001-r002",
        index=2,
    )
    adapter.drain_model_requests()
    adapter.on_raw_event(
        {
            "type": "response",
            "command": "prompt",
            "success": False,
            "error": "prompt rejected",
        }
    )
    adapter.on_raw_event(
        {
            "type": "auto_retry_end",
            "success": False,
            "attempt": 3,
            "maxAttempts": 3,
            "finalError": "retries exhausted",
        }
    )

    write_request_input(
        workspace,
        request_id="analysis-test-t001-r003",
        index=3,
    )
    adapter.drain_model_requests()
    adapter.end_turn()

    recorded = events(recorder)
    assert [event.event_type for event in recorded] == [
        "model.request.started",
        "model.response.failed",
        "model.retry.started",
        "model.request.started",
        "model.response.failed",
        "model.retry.exhausted",
        "model.request.started",
        "model.response.failed",
    ]
    retry = recorded[2]
    assert retry.payload == {
        "attempt": 1,
        "max_attempts": 3,
        "delay_seconds": 0.5,
        "message": "provider unavailable",
    }
    assert recorded[5].payload["message"] == "retries exhausted"
    assert recorded[-1].payload["error_type"] == "interrupted"


def test_tool_results_pair_by_call_id_when_completions_are_reordered(
    tmp_path: Path,
) -> None:
    recorder, adapter, _workspace = capture_with_active_request(tmp_path)
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-1",
            "tool_name": "grid_one",
            "args": {"branch": 1},
        },
        20,
    )
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-2",
            "tool_name": "grid_two",
            "args": {"branch": 2},
        },
        21,
    )
    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-2",
            "capability": "grid.two",
            "ok": True,
            "result": {},
            "evidence_refs": [],
        },
        22,
    )
    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-1",
            "capability": "grid.one",
            "ok": False,
            "result": {},
            "evidence_refs": [],
        },
        23,
    )

    completed = [event for event in events(recorder) if event.event_type == "tool.completed"]
    assert [event.scope.tool_call_id for event in completed] == ["call-2", "call-1"]
    starts = {
        event.scope.tool_call_id: event
        for event in events(recorder)
        if event.event_type == "tool.started"
    }
    assert completed[0].causation.parent_sequence == starts["call-2"].sequence
    assert completed[1].causation.parent_sequence == starts["call-1"].sequence


def test_successful_decision_tool_declares_bounded_agent_intent(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = capture_with_active_request(tmp_path)
    known_ref = "context:sha256:" + "c" * 64
    allowed_refs_path = workspace.root_path / "context" / "trajectory-allowed-refs.json"
    allowed_refs_path.write_text(
        json.dumps(
            {
                "schema_version": "grid-trajectory-allowed-refs/1.0",
                "refs": [known_ref],
            }
        ),
        encoding="utf-8",
    )
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "decision-1",
            "tool_name": "grid_record_decision",
            "args": {
                "intent": "Assess line 17 N-1 security",
                "decision": "Run the published contingency capability",
                "next_action": "Resolve line 17 and execute N-1",
                "refs": [known_ref],
            },
        },
        20,
    )
    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "decision-1",
            "tool_name": "grid_record_decision",
            "capability": "grid_record_decision",
            "ok": True,
            "result": {
                "intent": "Assess line 17 N-1 security",
                "decision": "Run the published contingency capability",
                "next_action": "Resolve line 17 and execute N-1",
                "refs": [known_ref],
            },
            "evidence_refs": [],
        },
        21,
    )

    recorded = events(recorder)
    completed = next(event for event in recorded if event.event_type == "tool.completed")
    declared = next(
        event for event in recorded if event.event_type == "business.decision.declared"
    )
    assert recorded.index(completed) < recorded.index(declared)
    assert declared.scope == completed.scope
    assert declared.causation.parent_sequence == completed.sequence
    assert declared.causation.correlation_id == "decision-1"
    assert declared.source.kind == "agent-declared"
    assert declared.source.producer == "grid-agent.pi-rpc"
    assert declared.refs.consumed == (known_ref,)
    assert declared.payload == {
        "intent": "Assess line 17 N-1 security",
        "decision": "Run the published contingency capability",
        "next_action": "Resolve line 17 and execute N-1",
    }


@pytest.mark.parametrize(
    "result",
    [
        {
            "intent": "x" * 501,
            "decision": "Run it",
            "next_action": "Continue",
            "refs": [],
        },
        {
            "intent": "Assess",
            "decision": "Run it",
            "next_action": "Continue",
            "refs": ["context:sha256:" + "f" * 64],
        },
    ],
)
def test_decision_declaration_rejects_unbounded_or_unknown_agent_values(
    tmp_path: Path,
    result: dict[str, object],
) -> None:
    recorder, adapter, workspace = capture_with_active_request(tmp_path)
    (workspace.root_path / "context" / "trajectory-allowed-refs.json").write_text(
        json.dumps(
            {
                "schema_version": "grid-trajectory-allowed-refs/1.0",
                "refs": [],
            }
        ),
        encoding="utf-8",
    )
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "decision-invalid",
            "tool_name": "grid_record_decision",
            "args": result,
        },
        20,
    )

    with pytest.raises(CaptureIntegrityError, match="decision"):
        adapter.on_semantic_event(
            {
                "event": "tool_result",
                "tool_call_id": "decision-invalid",
                "tool_name": "grid_record_decision",
                "capability": "grid_record_decision",
                "ok": True,
                "result": result,
                "evidence_refs": [],
            },
            21,
        )

    assert not any(
        event.event_type == "business.decision.declared" for event in events(recorder)
    )


@pytest.mark.parametrize(
    "semantic_event",
    [
        {
            "type": "tool_execution_start",
            "tool_name": "grid_one",
            "args": {},
        },
        {
            "event": "tool_result",
            "tool_call_id": "unknown-call",
            "capability": "grid.one",
            "ok": True,
            "result": {},
            "evidence_refs": [],
        },
    ],
)
def test_tool_pairing_rejects_missing_or_unknown_identity(
    tmp_path: Path, semantic_event: dict[str, object]
) -> None:
    _recorder, adapter, _workspace = capture_with_active_request(tmp_path)

    with pytest.raises(CaptureIntegrityError, match="tool_call_id"):
        adapter.on_semantic_event(semantic_event, 10)


def test_tool_completion_admits_exact_current_run_result_and_evidence(
    tmp_path: Path,
) -> None:
    recorder, adapter, workspace = capture_with_active_request(tmp_path)
    adapter.on_semantic_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-1",
            "tool_name": "grid_powerflow_run",
            "args": {},
        },
        10,
    )

    evidence_document = {
        "evidence_type": "network_fact",
        "capability_id": "topology.branch.endpoints.get",
        "context_ref": "context:sha256:" + "c" * 64,
        "revision_ref": "revision:sha256:" + "d" * 64,
    }
    evidence_digest = _sha256_canonical_json(evidence_document)
    evidence_ref = f"evidence:sha256:{evidence_digest}"
    evidence_path = (
        workspace.evidence_path
        / "network-facts"
        / f"network-fact-{evidence_digest}.json"
    )
    evidence_path.write_text(
        json.dumps(evidence_document, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    result_document = {
        "schema_version": "grid-result/1.0",
        "result_type": "powerflow",
        "context_ref": "context:sha256:" + "c" * 64,
        "revision_ref": "revision:sha256:" + "d" * 64,
        "evidence_refs": [evidence_ref],
        "payload": {},
    }
    result_digest = _sha256_canonical_json(result_document)
    result_ref = f"result:sha256:{result_digest}"
    result_document["result_ref"] = result_ref
    result_path = workspace.results_path / f"powerflow-{result_digest}.json"
    result_path.write_text(
        json.dumps(result_document, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    adapter.on_semantic_event(
        {
            "event": "tool_result",
            "tool_call_id": "call-1",
            "capability": "powerflow.run",
            "ok": True,
            "result": {"result_ref": result_ref},
            "evidence_refs": [evidence_ref],
        },
        11,
    )

    completed = events(recorder)[-1]
    assert completed.refs.produced == (result_ref,)
    assert completed.refs.evidence == (evidence_ref,)
    assert json.loads(result_path.read_text(encoding="utf-8")) == result_document


def test_capture_requires_monotonic_request_indexes_and_one_active_turn(
    tmp_path: Path,
) -> None:
    _recorder, adapter, workspace = native_capture_fixture(tmp_path)
    adapter.begin_turn("analysis-test-t001")
    with pytest.raises(CaptureIntegrityError, match="active turn"):
        adapter.begin_turn("analysis-test-t002")
    write_request_input(
        workspace,
        request_id="analysis-test-t001-r002",
        index=2,
    )
    adapter.drain_model_requests()
    write_request_input(
        workspace,
        request_id="analysis-test-t001-r001",
        index=1,
    )
    with pytest.raises(CaptureIntegrityError, match="monotonically increasing"):
        adapter.drain_model_requests()
