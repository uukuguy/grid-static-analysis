from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grid_agent.trajectory.context_projection import project_context
from grid_agent.trajectory.events import Causation, ContextBoundary, EventRefs, EventSource, RunScope


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


def test_context_frame_returns_before_delta_after_and_next_request_input() -> None:
    events = (
        Event(1, "context.projected", {"after_state": {"domain_state": {}}}, context=ContextBoundary(after_revision=1)),
        Event(4, "context.projected", {"after_state": {"domain_state": {"calculations": {"artifact:result": {"status": "converged"}}}}}, context=ContextBoundary(before_revision=1, after_revision=2)),
        Event(5, "model.request.started", {"artifact_ref": "artifact:request"}),
    )

    frame = project_context(events, artifacts=None, checkpoint_interval=2).at_sequence(4)

    assert frame.before_revision == 1
    assert frame.after_revision == 2
    assert frame.delta["domain_state"]["calculations"]["added"] == ("artifact:result",)
    assert frame.after_state["domain_state"]["calculations"]["artifact:result"]["status"] == "converged"
    assert frame.request_artifact_ref == "artifact:request"


def test_context_frame_labels_missing_request_unavailable() -> None:
    event = Event(8, "context.projected", {"after_state": {}}, context=ContextBoundary(before_revision=0, after_revision=1))
    frame = project_context((event,), artifacts=None).at_sequence(8)
    assert frame.request_artifact_ref is None
    assert frame.unavailable_reason == "legacy source did not capture model request input"
