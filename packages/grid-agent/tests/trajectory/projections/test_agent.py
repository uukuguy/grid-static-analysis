from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grid_agent.trajectory.agent_projection import project_agent
from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventRefs,
    EventSource,
    RunScope,
)


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
