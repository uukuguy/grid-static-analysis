from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grid_agent.trajectory.artifact_projection import project_artifacts
from grid_agent.trajectory.artifacts import ArtifactPointer
from grid_agent.trajectory.events import Causation, ContextBoundary, EventRefs, EventSource, RunScope


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: str
    refs: EventRefs = field(default_factory=EventRefs)
    analysis_id: str = "analysis-1"
    timestamp: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    scope: RunScope = field(default_factory=RunScope)
    causation: Causation = field(default_factory=Causation)
    source: EventSource = field(default_factory=EventSource)
    context: ContextBoundary = field(default_factory=ContextBoundary)


def test_artifact_index_is_bidirectional() -> None:
    pointer = ArtifactPointer("artifact:sha256:" + "a" * 64, "result", "evidence/results/powerflow-" + "a" * 64 + ".json", "a" * 64, 1)
    events = (
        Event(3, "tool.completed", refs=EventRefs(produced=(pointer.ref,)), scope=RunScope(turn_id="turn", step_id="step", request_id="request", tool_call_id="tool")),
        Event(5, "business.claim.declared", refs=EventRefs(consumed=(pointer.ref,))),
    )
    record = project_artifacts(events, _VerifiedRegistry(pointer)).records[pointer.ref]
    assert record.producing_sequence == 3
    assert record.consuming_sequences == (5,)
    assert record.tool_call_id == "tool"


def test_artifact_index_marks_unverifiable_references_unavailable() -> None:
    reference = "artifact:sha256:" + "b" * 64
    event = Event(3, "tool.completed", refs=EventRefs(produced=(reference,)))

    index = project_artifacts((event,), _BrokenRegistry())

    record = index.records[reference]
    assert record.status == "unavailable"
    assert record.verification_status == "unavailable"
    assert record.unavailable_reason == "artifact reference could not be verified"


class _BrokenRegistry:
    def verify_reference(self, reference: str) -> ArtifactPointer:
        raise RuntimeError(f"missing {reference}")


class _VerifiedRegistry:
    def __init__(self, pointer: ArtifactPointer) -> None:
        self.pointer = pointer

    def verify_reference(self, reference: str) -> ArtifactPointer:
        assert reference == self.pointer.ref
        return self.pointer
