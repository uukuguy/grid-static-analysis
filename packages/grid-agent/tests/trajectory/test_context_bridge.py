from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.analysis.view import materialize_context_view
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RunEventRecorder


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


def _bridge_type() -> type[Any]:
    try:
        from grid_agent.trajectory.context_bridge import NativeContextBridge
    except ModuleNotFoundError:
        pytest.fail("NativeContextBridge is not implemented")
    return NativeContextBridge


def bridge_fixture(
    tmp_path: Path,
) -> tuple[
    AnalysisWorkspace,
    RunEventRecorder,
    ImmutableArtifactRegistry,
    Any,
]:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
    )
    bridge = _bridge_type()(recorder, artifacts, workspace)
    return workspace, recorder, artifacts, bridge


def test_context_transition_commits_native_event_before_legacy_ledger(
    tmp_path: Path,
) -> None:
    workspace, recorder, _artifacts, bridge = bridge_fixture(tmp_path)
    observed: list[str] = []
    bridge.on_native_commit = lambda _event: observed.append("native")

    AnalysisContextStore.initialize(
        workspace,
        input_record=INPUT,
        runtime_record=RUNTIME,
        transition_commit=bridge.commit,
    )
    observed.append(
        "legacy" if workspace.context_events_path.exists() else "missing"
    )

    assert observed[:2] == ["native", "legacy"]
    prefix = RunEventReader(recorder.events_path).read_prefix()
    assert prefix.failure is None
    assert prefix.events[0].event_type == "analysis.started"


def test_bridge_updates_capture_state_after_each_context_event(
    tmp_path: Path,
) -> None:
    workspace, recorder, _artifacts, bridge = bridge_fixture(tmp_path)
    store = AnalysisContextStore.initialize(
        workspace,
        input_record=INPUT,
        runtime_record=RUNTIME,
        transition_commit=bridge.commit,
    )

    capture_state = json.loads(
        workspace.trajectory_capture_state_path.read_text(encoding="utf-8")
    )
    assert capture_state == {
        "source_event_sequences": [1],
        "context_revision": store.snapshot.revision,
        "context_state_hash": store.snapshot.state_hash,
    }

    materialize_context_view(store.snapshot, workspace.context_view_path)
    injected = bridge.record_injection(
        workspace.context_view_path, store.snapshot
    )
    capture_state = json.loads(
        workspace.trajectory_capture_state_path.read_text(encoding="utf-8")
    )
    assert capture_state["source_event_sequences"] == [injected.sequence]
    assert capture_state["context_revision"] == store.snapshot.revision
    assert capture_state["context_state_hash"] == store.snapshot.state_hash
    assert RunEventReader(recorder.events_path).read_prefix().failure is None


def test_context_injection_admits_immutable_exact_view_before_event(
    tmp_path: Path,
) -> None:
    workspace, recorder, artifacts, bridge = bridge_fixture(tmp_path)
    store = AnalysisContextStore.initialize(
        workspace,
        input_record=INPUT,
        runtime_record=RUNTIME,
        transition_commit=bridge.commit,
    )
    materialize_context_view(store.snapshot, workspace.context_view_path)
    exact_view = workspace.context_view_path.read_bytes()

    event = bridge.record_injection(
        workspace.context_view_path, store.snapshot
    )

    artifact_ref = event.payload["artifact_ref"]
    assert event.event_type == "context.injected"
    assert event.context.before_revision == store.snapshot.revision
    assert event.context.after_revision == store.snapshot.revision
    assert artifact_ref in event.refs.produced
    pointer = artifacts.verify_reference(artifact_ref)
    immutable_path = workspace.root_path / pointer.relative_path
    assert immutable_path.read_bytes() == exact_view
    assert immutable_path != workspace.context_view_path

    workspace.context_view_path.write_text('{"compatibility":"new"}\n')
    assert artifacts.verify_reference(artifact_ref) == pointer
    assert RunEventReader(recorder.events_path).read_prefix().failure is None
