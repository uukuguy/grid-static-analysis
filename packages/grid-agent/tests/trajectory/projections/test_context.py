from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, cast

from grid_agent.trajectory.context_projection import UNAVAILABLE_NATIVE_CONTEXT, project_context
from grid_agent.trajectory.artifacts import ArtifactPointer
from grid_agent.trajectory.events import Causation, ContextBoundary, EventRefs, EventSource, RunScope
from grid_agent.trajectory.replay import ReplayEventLike


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    scope: RunScope = field(default_factory=RunScope)
    analysis_id: str = "analysis-1"
    timestamp: str | None = None
    causation: Causation = field(default_factory=Causation)
    source: EventSource = field(default_factory=EventSource)
    context: ContextBoundary = field(default_factory=ContextBoundary)
    refs: EventRefs = field(default_factory=EventRefs)


def _replay_events(*events: Event) -> tuple[ReplayEventLike, ...]:
    return cast(tuple[ReplayEventLike, ...], events)


class VerifiedContextArtifacts:
    def __init__(self, pointer: ArtifactPointer, path: Path) -> None:
        self.pointer = pointer
        self.path = path
        self.references: list[str] = []

    def verify_reference(self, reference: str) -> ArtifactPointer:
        self.references.append(reference)
        if reference != self.pointer.ref:
            raise RuntimeError("unregistered artifact")
        return self.pointer

    def verify(self, pointer: ArtifactPointer) -> Path:
        assert pointer == self.pointer
        return self.path


def test_context_frame_returns_before_delta_after_and_next_request_input() -> None:
    events = (
        Event(1, "context.projected", {"after_state": {"domain_state": {}}}, context=ContextBoundary(after_revision=1)),
        Event(4, "context.projected", {"after_state": {"domain_state": {"calculations": {"artifact:result": {"status": "converged"}}}}}, context=ContextBoundary(before_revision=1, after_revision=2)),
        Event(5, "model.request.started", {"artifact_ref": "artifact:request"}),
    )

    frame = project_context(_replay_events(*events), artifacts=None, checkpoint_interval=2).at_sequence(4)

    assert frame.before_revision == 1
    assert frame.after_revision == 2
    assert frame.delta["domain_state"]["calculations"]["added"] == ("artifact:result",)
    assert frame.after_state["domain_state"]["calculations"]["artifact:result"]["status"] == "converged"
    assert frame.request_artifact_ref == "artifact:request"


def test_context_frame_labels_missing_request_unavailable() -> None:
    event = Event(8, "context.projected", {"after_state": {}}, context=ContextBoundary(before_revision=0, after_revision=1))
    frame = project_context(_replay_events(event), artifacts=None).at_sequence(8)
    assert frame.request_artifact_ref is None
    assert frame.unavailable_reason == "legacy source did not capture model request input"


def test_native_context_unavailable_preserves_next_request_artifact_reference() -> None:
    events = (
        Event(
            7,
            "context.injected",
            {"revision": 7, "state_hash": "sha256:state-7"},
            context=ContextBoundary(before_revision=7, after_revision=7),
        ),
        Event(8, "model.request.started", {"artifact_ref": "artifact:request-8"}),
    )

    frame = project_context(_replay_events(*events), artifacts=None).at_sequence(7)

    assert frame.status == "unavailable"
    assert frame.unavailable_reason == UNAVAILABLE_NATIVE_CONTEXT
    assert frame.request_artifact_ref == "artifact:request-8"
    assert frame.model_dump(mode="json")["after_state"] == {}


def test_native_context_injection_uses_verified_context_view_artifact(tmp_path: Path) -> None:
    document = {
        "schema_version": "analysis-context-view/1.0",
        "analysis_id": "analysis-1",
        "revision": 7,
        "state_hash": "sha256:state-7",
        "reusable_calculations": [{"result_ref": "result-7", "status": "converged"}],
    }
    path = tmp_path / "view.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    pointer = ArtifactPointer("artifact:sha256:" + "a" * 64, "context-view", "context/views/r7/view.json", "a" * 64, path.stat().st_size)
    artifacts = VerifiedContextArtifacts(pointer, path)
    event = Event(
        7,
        "context.injected",
        {"revision": 7, "state_hash": "sha256:state-7", "artifact_ref": pointer.ref},
        context=ContextBoundary(before_revision=7, after_revision=7),
        refs=EventRefs(produced=(pointer.ref,)),
    )

    frame = project_context(_replay_events(event), artifacts).at_sequence(7)

    assert artifacts.references == [pointer.ref]
    assert frame.model_dump(mode="json")["after_state"] == document
