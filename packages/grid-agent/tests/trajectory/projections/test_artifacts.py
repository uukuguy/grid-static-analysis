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
    record = project_artifacts(events, {pointer.ref: pointer}).records[pointer.ref]
    assert record.producing_sequence == 3
    assert record.consuming_sequences == (5,)
    assert record.tool_call_id == "tool"
