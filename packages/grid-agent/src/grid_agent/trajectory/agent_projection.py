"""Pure lifecycle projection for recorded agent events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from grid_agent.trajectory.projection_models import (
    AgentRetry,
    AgentStep,
    AgentTrajectory,
    AgentTurn,
    AssistantResponse,
    ExecutionSlice,
    LifecycleStatus,
    ModelRequest,
    ProjectedRun,
    ToolCall,
)
from grid_agent.trajectory.replay import ReplayEventLike


def _payload(event: ReplayEventLike) -> dict[str, Any]:
    return dict(event.payload)


@dataclass
class _ToolState:
    event: ReplayEventLike
    status: LifecycleStatus = "running"
    end: ReplayEventLike | None = None


@dataclass
class _RequestState:
    event: ReplayEventLike
    status: LifecycleStatus = "running"
    terminal: ReplayEventLike | None = None
    retries: list[tuple[ReplayEventLike, LifecycleStatus]] = field(default_factory=list)
    tools: dict[str, _ToolState] = field(default_factory=dict)
    tool_order: list[str] = field(default_factory=list)


@dataclass
class _StepState:
    event: ReplayEventLike
    status: LifecycleStatus = "running"
    terminal: ReplayEventLike | None = None
    request: _RequestState | None = None


@dataclass
class _TurnState:
    event: ReplayEventLike
    status: LifecycleStatus = "running"
    terminal: ReplayEventLike | None = None
    steps: dict[str, _StepState] = field(default_factory=dict)
    step_order: list[str] = field(default_factory=list)


class MutableAgentProjection:
    def __init__(self) -> None:
        self.analysis_id = ""
        self.turns: dict[str, _TurnState] = {}
        self.turn_order: list[str] = []
        self.closed = False

    def consume(self, event: ReplayEventLike) -> None:
        if not self.analysis_id:
            self.analysis_id = event.analysis_id
        handler = AGENT_HANDLERS.get(event.event_type)
        if handler is not None:
            handler(self, event)
        if event.event_type in {"analysis.completed", "analysis.failed"}:
            self.closed = True

    def close_at_boundary(self, last_event: ReplayEventLike | None) -> None:
        if last_event is None:
            return
        if last_event.event_type in {"analysis.completed", "analysis.failed"}:
            self.closed = True
        for turn in self.turns.values():
            if turn.terminal is not None:
                _interrupt_open_turn(turn)
        if self.closed:
            for turn in self.turns.values():
                _interrupt_open_turn(turn)

    def freeze(self) -> AgentTrajectory:
        return AgentTrajectory(
            analysis_id=self.analysis_id,
            turns=tuple(
                _freeze_turn(self.turns[turn_id]) for turn_id in self.turn_order
            ),
        )


def _start_turn(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    turn_id = event.scope.turn_id
    if turn_id is None or turn_id in state.turns:
        return
    state.turns[turn_id] = _TurnState(event)
    state.turn_order.append(turn_id)


def _complete_turn(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    turn = state.turns.get(event.scope.turn_id or "")
    if turn is not None:
        turn.status = "completed"
        turn.terminal = event


def _fail_turn(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    turn = state.turns.get(event.scope.turn_id or "")
    if turn is not None:
        turn.status = "failed"
        turn.terminal = event


def _start_step(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    turn = state.turns.get(event.scope.turn_id or "")
    step_id = event.scope.step_id
    if turn is None or step_id is None or step_id in turn.steps:
        return
    turn.steps[step_id] = _StepState(event)
    turn.step_order.append(step_id)


def _complete_step(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    step = _step_for(state, event)
    if step is not None:
        step.status, step.terminal = "completed", event


def _start_request(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    step = _step_for(state, event)
    if step is not None and step.request is None and event.scope.request_id is not None:
        step.request = _RequestState(event)


def _complete_response(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    if request is not None:
        request.status, request.terminal = "completed", event


def _fail_response(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    if request is not None:
        request.status, request.terminal = "failed", event


def _retry_scheduled(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    if request is not None:
        request.retries.append((event, "running"))


def _retry_started(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    if request is not None:
        request.retries.append((event, "running"))


def _retry_exhausted(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    if request is not None:
        request.retries.append((event, "failed"))


def _start_tool(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    request = _request_for(state, event)
    tool_id = event.scope.tool_call_id
    if request is None or tool_id is None or tool_id in request.tools:
        return
    request.tools[tool_id] = _ToolState(event)
    request.tool_order.append(tool_id)


def _complete_tool(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    _finish_tool(state, event, failed=not bool(_payload(event).get("ok")))


def _fail_tool(state: MutableAgentProjection, event: ReplayEventLike) -> None:
    _finish_tool(state, event, failed=True)


def _finish_tool(
    state: MutableAgentProjection, event: ReplayEventLike, *, failed: bool
) -> None:
    request = _request_for(state, event)
    if request is None:
        return
    tool = request.tools.get(event.scope.tool_call_id or "")
    if tool is not None and tool.end is None:
        tool.status = "failed" if failed else "completed"
        tool.end = event


def _step_for(
    state: MutableAgentProjection, event: ReplayEventLike
) -> _StepState | None:
    turn = state.turns.get(event.scope.turn_id or "")
    return turn.steps.get(event.scope.step_id or "") if turn is not None else None


def _request_for(
    state: MutableAgentProjection, event: ReplayEventLike
) -> _RequestState | None:
    step = _step_for(state, event)
    if step is None or step.request is None:
        return None
    return (
        step.request
        if step.request.event.scope.request_id == event.scope.request_id
        else None
    )


def _interrupt_open_turn(turn: _TurnState) -> None:
    if turn.terminal is None:
        turn.status = "interrupted"
    for step in turn.steps.values():
        if step.terminal is None:
            step.status = "interrupted"
        request = step.request
        if request is None:
            continue
        if request.terminal is None:
            request.status = "interrupted"
        for tool in request.tools.values():
            if tool.end is None:
                tool.status = "interrupted"


def _freeze_turn(state: _TurnState) -> AgentTurn:
    event = state.event
    return AgentTurn(
        id=f"agent:{event.analysis_id}:{event.scope.turn_id}",
        source="observed",
        source_sequences=(event.sequence,),
        status=state.status,
        turn_id=event.scope.turn_id or "unknown",
        ordinal=_payload(event).get("ordinal"),
        steps=tuple(_freeze_step(state.steps[key]) for key in state.step_order),
    )


def _freeze_step(state: _StepState) -> AgentStep:
    event = state.event
    return AgentStep(
        id=f"agent:{event.analysis_id}:{event.scope.step_id}",
        source="observed",
        source_sequences=(event.sequence,),
        status=state.status,
        step_id=event.scope.step_id or "unknown",
        request=_freeze_request(state.request) if state.request else None,
    )


def _freeze_request(state: _RequestState) -> ModelRequest:
    event, payload = state.event, _payload(state.event)
    sequences = [event.sequence]
    if state.terminal is not None:
        sequences.append(state.terminal.sequence)
    return ModelRequest(
        id=f"agent:{event.analysis_id}:{event.scope.request_id}",
        source="observed",
        source_sequences=tuple(sequences),
        status=state.status,
        request_id=event.scope.request_id or "unknown",
        artifact_ref=payload.get("artifact_ref"),
        retries=tuple(_freeze_retry(item) for item in state.retries),
        response=_freeze_response(state.terminal)
        if state.terminal and state.terminal.event_type == "model.response.completed"
        else None,
        tools=tuple(_freeze_tool(state.tools[key]) for key in state.tool_order),
    )


def _freeze_retry(item: tuple[ReplayEventLike, LifecycleStatus]) -> AgentRetry:
    event, status = item
    payload = _payload(event)
    return AgentRetry(
        id=f"agent:{event.analysis_id}:{event.sequence}:retry",
        source="observed",
        source_sequences=(event.sequence,),
        status=status,
        attempt=int(payload["attempt"]),
        max_attempts=int(payload["max_attempts"]),
        delay_seconds=payload.get("delay_seconds"),
        message=payload.get("message"),
    )


def _freeze_response(event: ReplayEventLike) -> AssistantResponse:
    payload = _payload(event)
    return AssistantResponse(
        id=f"agent:{event.analysis_id}:{event.sequence}:response",
        source="observed",
        source_sequences=(event.sequence,),
        status="completed",
        artifact_ref=payload.get("artifact_ref"),
        stop_reason=payload.get("stop_reason"),
        input_tokens=payload.get("input_tokens"),
        output_tokens=payload.get("output_tokens"),
        ttft_seconds=payload.get("ttft_seconds"),
        duration_seconds=payload.get("duration_seconds"),
    )


def _freeze_tool(state: _ToolState) -> ToolCall:
    event, payload = state.event, _payload(state.event)
    end_payload = _payload(state.end) if state.end is not None else {}
    sequences = (
        (event.sequence,) if state.end is None else (event.sequence, state.end.sequence)
    )
    return ToolCall(
        id=f"agent:{event.analysis_id}:{event.scope.tool_call_id}",
        source="observed",
        source_sequences=sequences,
        status=state.status,
        tool_call_id=event.scope.tool_call_id or "unknown",
        capability=str(payload["capability"]),
        start_sequence=event.sequence,
        end_sequence=state.end.sequence if state.end else None,
        artifact_ref=end_payload.get("artifact_ref", payload.get("artifact_ref")),
        ok=end_payload.get("ok"),
        duration_seconds=end_payload.get("duration_seconds"),
    )


AGENT_HANDLERS = {
    "turn.started": _start_turn,
    "turn.completed": _complete_turn,
    "turn.failed": _fail_turn,
    "step.started": _start_step,
    "step.completed": _complete_step,
    "model.request.started": _start_request,
    "model.response.completed": _complete_response,
    "model.response.failed": _fail_response,
    "model.retry.scheduled": _retry_scheduled,
    "model.retry.started": _retry_started,
    "model.retry.exhausted": _retry_exhausted,
    "tool.started": _start_tool,
    "tool.completed": _complete_tool,
    "tool.failed": _fail_tool,
}


def project_agent(events: Sequence[ReplayEventLike]) -> AgentTrajectory:
    state = MutableAgentProjection()
    for event in events:
        state.consume(event)
    state.close_at_boundary(events[-1] if events else None)
    return state.freeze()


def execution_slice(projected: ProjectedRun, sequence: int) -> ExecutionSlice:
    """Return the owning turn only when a typed agent node records the sequence."""
    for turn in projected.agent.turns:
        if _turn_contains_sequence(turn, sequence):
            return ExecutionSlice(
                analysis_id=projected.analysis_id,
                source_sequence=sequence,
                turn=turn,
                unavailable_reason=None,
            )
    return ExecutionSlice(
        analysis_id=projected.analysis_id,
        source_sequence=sequence,
        turn=None,
        unavailable_reason="no durable execution linkage is recorded",
    )


def _turn_contains_sequence(turn: AgentTurn, sequence: int) -> bool:
    if sequence in turn.source_sequences:
        return True
    for step in turn.steps:
        if _step_contains_sequence(step, sequence):
            return True
    return False


def _step_contains_sequence(step: AgentStep, sequence: int) -> bool:
    if sequence in step.source_sequences:
        return True
    return step.request is not None and _request_contains_sequence(step.request, sequence)


def _request_contains_sequence(request: ModelRequest, sequence: int) -> bool:
    if sequence in request.source_sequences:
        return True
    if any(sequence in retry.source_sequences for retry in request.retries):
        return True
    if request.response is not None and sequence in request.response.source_sequences:
        return True
    return any(sequence in tool.source_sequences for tool in request.tools)
