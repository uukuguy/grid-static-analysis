from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.integrity import ReferenceDiagnostic
from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.analysis import turns as turns_module
from grid_agent.analysis.turns import ActiveTurnHandle, StaleAnswerDraftError, TurnController
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.context_bridge import NativeContextBridge
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RunEventRecorder


INPUT = {
    "copied_path": "input/instructions.md.txt",
    "source_path": "task.md.txt",
    "sha256": "a" * 64,
    "instruction_count": 2,
}

RUNTIME = {
    "provider": "test",
    "model": "scripted",
    "grid_capability_protocol": "1.0",
    "pandapower_version": "3.4.0",
}


@dataclass(frozen=True, slots=True)
class Harness:
    workspace: AnalysisWorkspace
    store: AnalysisContextStore
    turns: TurnController


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    turns = TurnController(workspace, store, audit_callback=lambda _claimed, _results: ())
    return Harness(workspace=workspace, store=store, turns=turns)


def test_turn_controller_archives_controller_owned_submissions(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    harness.turns.submit(first, answer_output="第一答", duration_seconds=1.0)
    second = harness.turns.start(2, "第二条")
    completed = harness.turns.submit(second, answer_output="第二答", duration_seconds=1.2)

    assert completed.answer_output == "第二答"
    assert json.loads((harness.workspace.turn_path(2) / "answer.json").read_text(encoding="utf-8"))[
        "answer_output"
    ] == "第二答"
    assert [json.loads(line)["answer_output"] for line in harness.workspace.answers_path.read_text().splitlines()] == [
        "第一答",
        "第二答",
    ]


def test_turn_controller_archives_audit_diagnostics_without_mutating_answer(harness: Harness) -> None:
    diagnostic = ReferenceDiagnostic(
        category="missing_evidence",
        severity="error",
        reference="evidence:sha256:" + "f" * 64,
        message="claimed evidence ref is not in the current run",
        impact="impact",
        remediation="remediation",
    )
    turns = TurnController(harness.workspace, harness.store, audit_callback=lambda _claimed, _results: (diagnostic,))
    turn = turns.start(1, "引用证据")

    completed = turns.submit(
        turn,
        answer_output="保持原文 result:sha256:" + "a" * 64,
        duration_seconds=0.5,
    )

    assert completed.answer_output == "保持原文 result:sha256:" + "a" * 64
    assert diagnostic in completed.audit_diagnostics
    assert json.loads((harness.workspace.turn_path(1) / "answer.json").read_text(encoding="utf-8"))[
        "answer_output"
    ] == completed.answer_output
    assert json.loads(harness.workspace.answers_path.read_text(encoding="utf-8"))["answer_output"] == completed.answer_output
    audit = json.loads((harness.workspace.turn_path(1) / "answer-audit.json").read_text(encoding="utf-8"))
    assert any(item["message"] == diagnostic.message for item in audit["diagnostics"])
    assert harness.store.snapshot.diagnostics[-1].event_type == "audit.diagnostic.recorded"
    assert harness.store.snapshot.turns[-1].status == "success"


def test_turn_start_atomically_replaces_active_turn_and_clears_active_draft(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    stale_draft = harness.workspace.active_answer_draft_path
    write_draft(stale_draft, first, answer="未完成")
    harness.turns.fail(first, error="model stopped", duration_seconds=0.1)

    second = harness.turns.start(2, "第二条")

    active_turn = json.loads(harness.workspace.active_turn_path.read_text(encoding="utf-8"))
    assert active_turn["turn_id"] == second.turn_id
    assert active_turn["turn_nonce"] == second.turn_nonce
    assert active_turn["turn_id"] != first.turn_id
    assert not stale_draft.exists()
    assert not list(harness.workspace.root_path.glob(".active-turn.json*.tmp"))


def test_turn_start_while_store_turn_active_preserves_active_files_and_context(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    write_draft(harness.workspace.active_answer_draft_path, first, answer="草稿")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    with pytest.raises(RuntimeError, match="active turn"):
        harness.turns.start(2, "第二条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_start_preserves_active_files_when_store_append_fails(harness: Harness) -> None:
    harness.workspace.active_turn_path.write_text('{"turn_id":"previous"}\n', encoding="utf-8")
    harness.workspace.active_answer_draft_path.write_text('{"answer_output":"previous"}\n', encoding="utf-8")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    def fail_append(*args, **kwargs):
        raise RuntimeError("store append failed")

    harness.store.append = fail_append

    with pytest.raises(RuntimeError, match="store append failed"):
        harness.turns.start(1, "第一条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_start_preserves_active_files_and_context_when_filesystem_activation_fails(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.workspace.active_turn_path.write_text('{"turn_id":"previous"}\n', encoding="utf-8")
    harness.workspace.active_answer_draft_path.write_text('{"answer_output":"previous"}\n', encoding="utf-8")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    def fail_active_record_write(path: Path, payload: object) -> bytes:
        if path == harness.workspace.active_turn_path:
            raise OSError("simulated active turn write failure")
        raise AssertionError(f"unexpected JSON write: {path}")

    monkeypatch.setattr(turns_module, "_write_json_atomic", fail_active_record_write)

    with pytest.raises(OSError, match="simulated active turn write failure"):
        harness.turns.start(1, "第一条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_context_hashes_nonce_without_recording_raw_nonce(harness: Harness) -> None:
    turn = harness.turns.start(1, "哈希 nonce")

    snapshot_text = harness.workspace.context_snapshot_path.read_text(encoding="utf-8")
    events_text = harness.workspace.context_events_path.read_text(encoding="utf-8")

    assert turn.turn_nonce in harness.workspace.active_turn_path.read_text(encoding="utf-8")
    assert turn.turn_nonce not in snapshot_text
    assert turn.turn_nonce not in events_text
    assert harness.store.snapshot.current_turn is not None
    assert harness.store.snapshot.current_turn.nonce_sha256 == sha256(turn.turn_nonce.encode("utf-8")).hexdigest()


def test_controller_submits_model_text_with_projected_turn_refs(tmp_path: Path) -> None:
    controller, recorder, store, workspace, handle, result_ref, evidence_ref = answer_fixture(tmp_path)
    register_answer_lineage(store, handle, result_ref, evidence_ref)

    completed = controller.submit(
        handle,
        answer_output="线路结果来自本题仿真。",
        duration_seconds=1.0,
    )

    draft = json.loads(
        (workspace.turn_path(1) / "answer-draft.json").read_text(encoding="utf-8")
    )
    assert completed.status == "success"
    assert completed.answer_output == "线路结果来自本题仿真。"
    assert draft["turn_id"] == handle.turn_id
    assert draft["turn_nonce"] == handle.turn_nonce
    assert draft["result_refs"] == [result_ref]
    assert draft["claim_evidence_refs"] == [evidence_ref]
    assert draft["claims"] == []
    events = RunEventReader(recorder.events_path).read_prefix().events
    assert not any(event.event_type == "business.claim.declared" for event in events)


def test_controller_submission_keeps_only_result_and_evidence_refs() -> None:
    refs = turns_module._answer_level_refs(
        (
            "context:sha256:" + "1" * 64,
            "result:sha256:" + "2" * 64,
            "evidence:sha256:" + "3" * 64,
            "result:sha256:" + "2" * 64,
            "observation:sha256:" + "4" * 64,
        )
    )
    assert refs == (
        ("result:sha256:" + "2" * 64,),
        ("evidence:sha256:" + "3" * 64,),
    )


def test_controller_rejects_empty_model_final_text(harness: Harness) -> None:
    turn = harness.turns.start(1, "没有最终文本")

    finalized = harness.turns.submit(
        turn,
        answer_output="  \n",
        duration_seconds=0.5,
    )

    assert finalized.status == "failed"
    assert finalized.error == "model returned no final answer"
    assert harness.store.snapshot.turns[-1].status == "failed"
    assert not (harness.workspace.turn_path(1) / "answer.json").exists()


def test_controller_rejects_submit_handle_with_wrong_nonce(
    tmp_path: Path,
) -> None:
    controller, _recorder, store, _workspace, handle, result_ref, evidence_ref = answer_fixture(tmp_path)
    register_answer_lineage(store, handle, result_ref, evidence_ref)
    forged_handle = ActiveTurnHandle(
        ordinal=handle.ordinal,
        turn_id=handle.turn_id,
        instruction=handle.instruction,
        instruction_sha256=handle.instruction_sha256,
        turn_nonce="forged-turn-nonce",
        started_monotonic=handle.started_monotonic,
    )

    with pytest.raises(
        StaleAnswerDraftError,
        match="answer submission is bound to a different turn",
    ):
        controller.submit(
            forged_handle,
            answer_output="线路结果来自本题仿真。",
            duration_seconds=1.0,
        )


def test_answer_commit_failure_emits_no_accepted_answer(
    tmp_path: Path,
) -> None:
    controller, recorder, store, _workspace, handle, result_ref, evidence_ref = answer_fixture(tmp_path)
    register_answer_lineage(store, handle, result_ref, evidence_ref)
    original_append = store.append

    def fail_answer_commit(draft, **kwargs):
        if draft.event_type == "answer.submitted":
            raise RuntimeError("answer commit failed")
        return original_append(draft, **kwargs)

    store.append = fail_answer_commit

    with pytest.raises(RuntimeError, match="answer commit failed"):
        controller.submit(
            handle,
            answer_output="线路结果来自本题仿真。",
            duration_seconds=1.0,
        )

    events = RunEventReader(recorder.events_path).read_prefix().events
    assert not any(event.event_type == "business.claim.declared" for event in events)
    assert not any(event.event_type == "answer.submitted" for event in events)


class AcceptingVerifier:
    def verify_result(self, reference: str) -> object:
        return reference

    def verify_evidence(self, reference: str) -> object:
        return reference


def answer_fixture(
    tmp_path: Path,
):
    result_ref = "result:sha256:" + "a" * 64
    evidence_ref = "evidence:sha256:" + "b" * 64
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-answer")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    bridge = NativeContextBridge(recorder, artifacts, workspace)
    store = AnalysisContextStore.initialize(
        workspace,
        input_record=INPUT,
        runtime_record=RUNTIME,
        transition_commit=bridge.commit,
    )
    controller = TurnController(
        workspace,
        store,
        audit_callback=lambda _claimed, _results: (),
        verifier=AcceptingVerifier(),
        allowed_refs={result_ref, evidence_ref},
        recorder=recorder,
    )
    handle = controller.start(1, "Assess line 11")
    return controller, recorder, store, workspace, handle, result_ref, evidence_ref


def register_answer_lineage(
    store: AnalysisContextStore,
    handle,
    result_ref: str,
    evidence_ref: str,
) -> None:
    store.append(
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id=handle.turn_id,
            capability="context.open",
            payload={
                "context_ref": "context:sha256:" + "1" * 64,
                "revision_ref": "revision:sha256:" + "2" * 64,
                "path": "evidence/contexts/context.json",
                "source": {
                    "capability": "context.open",
                    "grid_capability_protocol": "1.0",
                    "pandapower_version": "3.4.0",
                },
                "network": {
                    "name": "case-test",
                    "bus_count": 3,
                    "line_count": 2,
                    "trafo_count": 0,
                },
            },
        )
    )
    store.append(
        ContextEventDraft(
            event_type="result.registered",
            turn_id=handle.turn_id,
            capability="analysis.powerflow.ac.run",
            payload={
                "result_ref": result_ref,
                "revision_ref": "revision:sha256:" + "2" * 64,
                "path": "evidence/results/powerflow.json",
                "evidence_refs": [evidence_ref],
                "solver_summary": {
                    "success": True,
                    "algorithm": "nr",
                    "iterations": 3,
                    "total_loss_mw": 0.125,
                },
                "producer_observation": {
                    "capability": "analysis.powerflow.ac.run",
                    "grid_capability_protocol": "1.0",
                    "pandapower_version": "3.4.0",
                },
            },
        )
    )
    store.append(
        ContextEventDraft(
            event_type="evidence.registered",
            turn_id=handle.turn_id,
            capability="gridctl.evidence.register",
            payload={
                "evidence_ref": evidence_ref,
                "path": "evidence/network-facts/powerflow-fact.json",
                "kind": "simulator",
                "refs": [result_ref],
                "summary": {
                    "provenance": "gridctl",
                    "description": "deterministic simulator evidence",
                },
            },
        )
    )


def write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_draft(
    path: Path,
    turn,
    *,
    answer: str,
    claim_evidence_refs: list[str] | None = None,
    result_refs: list[str] | None = None,
) -> None:
    write_raw_draft(
        path,
        turn_id=turn.turn_id,
        turn_nonce=turn.turn_nonce,
        answer=answer,
        claim_evidence_refs=claim_evidence_refs,
        result_refs=result_refs,
    )


def write_raw_draft(
    path: Path,
    *,
    turn_id: str,
    turn_nonce: str,
    answer: str,
    claim_evidence_refs: list[str] | None = None,
    result_refs: list[str] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "turn_id": turn_id,
                "turn_nonce": turn_nonce,
                "answer_output": answer,
                "claim_evidence_refs": claim_evidence_refs or [],
                "result_refs": result_refs or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
