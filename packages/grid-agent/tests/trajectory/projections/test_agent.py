from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grid_agent.trajectory.agent_projection import execution_slice, project_agent
from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventRefs,
    EventSource,
    RunScope,
)
from grid_agent.trajectory.projection_models import ArtifactIndex, BusinessTrajectory, ContextTimeline, ProjectedRun


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: str
    scope: RunScope = field(default_factory=RunScope)
    payload: dict[str, Any] = field(default_factory=dict)
    analysis_id: str = "analysis-1"
    timestamp: str | None = None
    causation: Causation = field(default_factory=Causation)
    source: EventSource = field(default_factory=EventSource)
    context: ContextBoundary = field(default_factory=ContextBoundary)
    refs: EventRefs = field(default_factory=EventRefs)


def test_agent_projection_pairs_tools_by_id_not_adjacency() -> None:
    events = (
        Event(1, "turn.started", RunScope(turn_id="turn-1"), {"ordinal": 1}),
        Event(2, "step.started", RunScope(turn_id="turn-1", step_id="step-1")),
        Event(
            3,
            "model.request.started",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
        ),
        Event(
            4,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-a",
            ),
            {"capability": "context.open"},
        ),
        Event(
            5,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-b",
            ),
            {"capability": "model.list"},
        ),
        Event(
            6,
            "tool.completed",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-b",
            ),
            {"capability": "model.list", "ok": False},
        ),
        Event(
            7,
            "tool.completed",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-a",
            ),
            {"capability": "context.open", "ok": True},
        ),
    )

    request = project_agent(events).turns[0].steps[0].request

    assert request is not None
    assert [(tool.tool_call_id, tool.status) for tool in request.tools] == [
        ("call-a", "completed"),
        ("call-b", "failed"),
    ]
    assert request.tools[0].start_sequence == 4
    assert request.tools[0].end_sequence == 7


def test_agent_projection_marks_open_tool_interrupted_only_after_closed_run() -> None:
    events = (
        Event(1, "turn.started", RunScope(turn_id="turn-1"), {"ordinal": 1}),
        Event(2, "step.started", RunScope(turn_id="turn-1", step_id="step-1")),
        Event(
            3,
            "model.request.started",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
        ),
        Event(
            4,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-a",
            ),
            {"capability": "context.open"},
        ),
        Event(5, "turn.completed", RunScope(turn_id="turn-1"), {"status": "success"}),
    )

    tool = project_agent(events).turns[0].steps[0].request.tools[0]  # type: ignore[union-attr]

    assert tool.status == "interrupted"
    assert tool.duration_seconds is None


def test_agent_projection_nests_retries_under_the_request() -> None:
    events = (
        Event(1, "turn.started", RunScope(turn_id="turn-1"), {"ordinal": 1}),
        Event(2, "step.started", RunScope(turn_id="turn-1", step_id="step-1")),
        Event(
            3,
            "model.request.started",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
        ),
        Event(
            4,
            "model.retry.scheduled",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
            {"attempt": 1, "max_attempts": 2, "delay_seconds": 0.5},
        ),
    )

    request = project_agent(events).turns[0].steps[0].request

    assert request is not None
    assert [(retry.attempt, retry.status) for retry in request.retries] == [
        (1, "running")
    ]


def test_agent_projection_interrupts_every_open_descendant_when_analysis_closes() -> None:
    events = (
        Event(1, "turn.started", RunScope(turn_id="turn-1"), {"ordinal": 1}),
        Event(2, "step.started", RunScope(turn_id="turn-1", step_id="step-1")),
        Event(
            3,
            "model.request.started",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
        ),
        Event(
            4,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="call-1",
            ),
            {"capability": "context.open"},
        ),
        Event(5, "analysis.completed", payload={}),
    )

    turn = project_agent(events).turns[0]

    assert turn.status == "interrupted"
    assert turn.steps[0].status == "interrupted"
    assert turn.steps[0].request is not None
    assert turn.steps[0].request.status == "interrupted"
    assert turn.steps[0].request.tools[0].status == "interrupted"


def test_execution_slice_uses_nested_source_sequences_without_nearest_fallback() -> None:
    events = (
        Event(10, "turn.started", RunScope(turn_id="turn-1"), {"ordinal": 1}),
        Event(11, "step.started", RunScope(turn_id="turn-1", step_id="step-1")),
        Event(
            12,
            "model.request.started",
            RunScope(turn_id="turn-1", step_id="step-1", request_id="request-1"),
        ),
        Event(20, "turn.started", RunScope(turn_id="turn-2"), {"ordinal": 2}),
        Event(
            21,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="tool-1",
            ),
            {"capability": "grid.analyze"},
        ),
        Event(
            22,
            "tool.completed",
            RunScope(
                turn_id="turn-1",
                step_id="step-1",
                request_id="request-1",
                tool_call_id="tool-1",
            ),
            {"capability": "grid.analyze", "ok": True},
        ),
        Event(23, "step.started", RunScope(turn_id="turn-1", step_id="step-unrelated")),
        Event(
            24,
            "model.request.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-unrelated",
                request_id="request-unrelated",
            ),
        ),
        Event(
            25,
            "tool.started",
            RunScope(
                turn_id="turn-1",
                step_id="step-unrelated",
                request_id="request-unrelated",
                tool_call_id="tool-unrelated",
            ),
            {"capability": "provider_payload.unrelated"},
        ),
        Event(
            26,
            "tool.completed",
            RunScope(
                turn_id="turn-1",
                step_id="step-unrelated",
                request_id="request-unrelated",
                tool_call_id="tool-unrelated",
            ),
            {"capability": "provider_payload.unrelated", "ok": True},
        ),
    )
    projected = ProjectedRun(
        analysis_id="analysis-1",
        source_fingerprint="sha256:source",
        agent=project_agent(events),
        business=BusinessTrajectory(analysis_id="analysis-1"),
        context=ContextTimeline(analysis_id="analysis-1"),
        artifacts=ArtifactIndex(analysis_id="analysis-1"),
    )

    linked = execution_slice(projected, 22)
    turn_level = execution_slice(projected, 10)
    missing = execution_slice(projected, 19)

    assert linked.turn is not None
    assert linked.turn.turn_id == "turn-1"
    assert [step.step_id for step in linked.turn.steps] == ["step-1"]
    assert linked.turn.steps[0].request is not None
    assert [tool.tool_call_id for tool in linked.turn.steps[0].request.tools] == [
        "tool-1"
    ]
    assert turn_level.turn is not None
    assert turn_level.turn.turn_id == "turn-1"
    assert turn_level.turn.steps == ()
    assert missing.turn is None
    assert missing.unavailable_reason == "no durable execution linkage is recorded"
