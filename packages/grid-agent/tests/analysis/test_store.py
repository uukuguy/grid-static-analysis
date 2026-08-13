from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.store import AnalysisContextStore, ContextStoreError
from grid_agent.analysis.workspace import AnalysisWorkspace


INPUT = {
    "copied_path": "input/instructions.md.txt",
    "source_path": "task.md.txt",
    "sha256": "a" * 64,
    "instruction_count": 1,
}

RUNTIME = {
    "provider": "test",
    "model": "scripted",
    "grid_capability_protocol": "1.0",
    "pandapower_version": "3.4.0",
}

TURN_START = {
    "ordinal": 1,
    "instruction": "run a deterministic check",
    "instruction_sha256": "b" * 64,
    "nonce_sha256": "c" * 64,
}

TURN_COMPLETE = {
    "status": "success",
    "answer_path": "turns/001/answer.json",
    "answer_sha256": "d" * 64,
    "duration_seconds": 1.25,
}


def test_store_replays_ledger_to_identical_snapshot(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    first = store.append(
        ContextEventDraft(event_type="turn.started", turn_id="analysis-test-t001", payload=TURN_START)
    )
    second = store.append(
        ContextEventDraft(event_type="turn.completed", turn_id="analysis-test-t001", payload=TURN_COMPLETE)
    )

    replayed = AnalysisContextStore.replay(workspace.context_events_path)

    assert first.sequence == 2  # analysis.started is sequence 1
    assert second.previous_state_hash == first.next_state_hash
    assert replayed == store.snapshot
    assert json.loads(workspace.context_snapshot_path.read_text(encoding="utf-8")) == store.snapshot.model_dump(
        mode="json"
    )


def test_initialize_writes_replayable_analysis_started_event(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)

    [event] = [
        json.loads(line)
        for line in workspace.context_events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert event["event_type"] == "analysis.started"
    assert event["sequence"] == 1
    assert event["previous_revision"] == 0
    assert event["next_revision"] == 1
    assert event["payload"] == {"input": INPUT, "runtime": RUNTIME}
    assert store.snapshot.status == "running"


def test_replay_rejects_truncated_final_ledger_line(tmp_path: Path) -> None:
    workspace, _store = _workspace_with_completed_turn(tmp_path)
    content = workspace.context_events_path.read_text(encoding="utf-8")
    workspace.context_events_path.write_text(content.rsplit("\n", 2)[0] + '\n{"sequence":', encoding="utf-8")

    with pytest.raises(ContextStoreError, match="malformed ledger line"):
        AnalysisContextStore.replay(workspace.context_events_path)


def test_replay_rejects_sequence_gap(tmp_path: Path) -> None:
    workspace, _store = _workspace_with_completed_turn(tmp_path)
    events = _read_ledger_events(workspace)
    events[1]["sequence"] = 4
    _write_ledger_events(workspace, events)

    with pytest.raises(ContextStoreError, match="sequence"):
        AnalysisContextStore.replay(workspace.context_events_path)


def test_replay_rejects_previous_hash_mismatch(tmp_path: Path) -> None:
    workspace, _store = _workspace_with_completed_turn(tmp_path)
    events = _read_ledger_events(workspace)
    events[1]["previous_state_hash"] = "0" * 64
    _write_ledger_events(workspace, events)

    with pytest.raises(ContextStoreError, match="previous_state_hash"):
        AnalysisContextStore.replay(workspace.context_events_path)


def test_verify_materialized_snapshot_rejects_modified_snapshot(tmp_path: Path) -> None:
    workspace, store = _workspace_with_completed_turn(tmp_path)
    snapshot = json.loads(workspace.context_snapshot_path.read_text(encoding="utf-8"))
    snapshot["status"] = "failed"
    workspace.context_snapshot_path.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ContextStoreError, match="snapshot"):
        store.verify_materialized_snapshot()


def _workspace_with_completed_turn(tmp_path: Path) -> tuple[AnalysisWorkspace, AnalysisContextStore]:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    store.append(ContextEventDraft(event_type="turn.started", turn_id="analysis-test-t001", payload=TURN_START))
    store.append(ContextEventDraft(event_type="turn.completed", turn_id="analysis-test-t001", payload=TURN_COMPLETE))
    return workspace, store


def _read_ledger_events(workspace: AnalysisWorkspace) -> list[dict[str, object]]:
    return [json.loads(line) for line in workspace.context_events_path.read_text(encoding="utf-8").splitlines()]


def _write_ledger_events(workspace: AnalysisWorkspace, events: list[dict[str, object]]) -> None:
    workspace.context_events_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )
