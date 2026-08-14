"""Stable, frozen output models for the trajectory projection boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, model_validator

from grid_agent.trajectory.events import StrictFrozenModel


class _FrozenDict(dict[str, Any]):
    """A JSON-compatible dictionary that rejects every in-place mutation."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        dict.__init__(self, values)

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable  # type: ignore[reportAssignmentType]
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[reportAssignmentType]
    setdefault = _immutable  # type: ignore[reportAssignmentType]
    update = _immutable  # type: ignore[reportAssignmentType]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


NodeSource = Literal["observed", "agent-declared", "derived"]
LifecycleStatus = Literal[
    "running", "completed", "failed", "interrupted", "unavailable"
]


class ProjectionNode(StrictFrozenModel):
    """The provenance fields shared by every projected node."""

    id: str = Field(min_length=1)
    source: NodeSource
    source_sequences: tuple[int, ...] = ()
    rule_id: str | None = Field(default=None, min_length=1)
    status: LifecycleStatus
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def require_source_sequences(self) -> "ProjectionNode":
        if not self.source_sequences:
            raise ValueError("projection node requires source_sequences")
        if any(sequence < 1 for sequence in self.source_sequences):
            raise ValueError("source_sequences must contain positive sequence numbers")
        if self.source == "derived" and self.rule_id is None:
            raise ValueError("derived node requires rule_id")
        if self.source != "derived" and self.rule_id is not None:
            raise ValueError("observed or agent-declared node must not have rule_id")
        return self


class AgentRetry(ProjectionNode):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    delay_seconds: float | None = Field(default=None, ge=0)
    message: str | None = None

    @model_validator(mode="after")
    def require_valid_attempt(self) -> "AgentRetry":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt must not exceed max_attempts")
        return self


class AssistantResponse(ProjectionNode):
    artifact_ref: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    ttft_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class ToolCall(ProjectionNode):
    tool_call_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    start_sequence: int = Field(ge=1)
    end_sequence: int | None = Field(default=None, ge=1)
    artifact_ref: str | None = None
    ok: bool | None = None
    duration_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_ordered_lifecycle(self) -> "ToolCall":
        if self.end_sequence is not None and self.end_sequence < self.start_sequence:
            raise ValueError("end_sequence must not precede start_sequence")
        return self


class ModelRequest(ProjectionNode):
    request_id: str = Field(min_length=1)
    artifact_ref: str | None = None
    retries: tuple[AgentRetry, ...] = ()
    response: AssistantResponse | None = None
    tools: tuple[ToolCall, ...] = ()


class AgentStep(ProjectionNode):
    step_id: str = Field(min_length=1)
    request: ModelRequest | None = None


class AgentTurn(ProjectionNode):
    turn_id: str = Field(min_length=1)
    ordinal: int | None = Field(default=None, ge=1)
    steps: tuple[AgentStep, ...] = ()


class AgentTrajectory(StrictFrozenModel):
    analysis_id: str = Field(min_length=1)
    turns: tuple[AgentTurn, ...] = ()


class BusinessNode(ProjectionNode):
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    detail: str | None = None
    refs: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def reject_unproven_derived_node(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("source") == "derived":
            if not value.get("source_sequences") or not value.get("rule_id"):
                raise ValueError("derived node requires source_sequences and rule_id")
        return value

class BusinessProblem(ProjectionNode):
    turn_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    nodes: tuple[BusinessNode, ...] = ()


class BusinessTrajectory(StrictFrozenModel):
    analysis_id: str = Field(min_length=1)
    problems: tuple[BusinessProblem, ...] = ()


class ContextFrame(ProjectionNode):
    source: NodeSource = "derived"
    status: LifecycleStatus = "completed"
    source_sequence: int = Field(ge=1)
    before_revision: int = Field(ge=0)
    after_revision: int = Field(ge=0)
    before_state_hash: str = Field(min_length=1)
    after_state_hash: str = Field(min_length=1)
    before_state: Mapping[str, Any]
    delta: Mapping[str, Any]
    after_state: Mapping[str, Any]
    request_artifact_ref: str | None = None

    @model_validator(mode="after")
    def require_consistent_frame(self) -> "ContextFrame":
        if self.before_revision > self.after_revision:
            raise ValueError("before_revision must not exceed after_revision")
        if self.source_sequences and self.source_sequence not in self.source_sequences:
            raise ValueError("source_sequences must include source_sequence")
        if self.request_artifact_ref is None and not self.unavailable_reason:
            raise ValueError("unavailable_reason is required when request_artifact_ref is null")
        if self.request_artifact_ref is not None and self.unavailable_reason is not None:
            raise ValueError("unavailable_reason requires a null request_artifact_ref")
        return self

    @model_validator(mode="after")
    def freeze_states(self) -> "ContextFrame":
        object.__setattr__(self, "before_state", _deep_freeze(self.before_state))
        object.__setattr__(self, "delta", _deep_freeze(self.delta))
        object.__setattr__(self, "after_state", _deep_freeze(self.after_state))
        return self


class ContextCheckpoint(StrictFrozenModel):
    source_sequence: int = Field(ge=1)
    context_revision: int = Field(ge=0)
    state_hash: str = Field(min_length=1)
    state: Mapping[str, Any]

    @model_validator(mode="after")
    def freeze_state(self) -> "ContextCheckpoint":
        object.__setattr__(self, "state", _deep_freeze(self.state))
        return self


class ContextTimeline(StrictFrozenModel):
    analysis_id: str = Field(min_length=1)
    frames: tuple[ContextFrame, ...] = ()
    checkpoints: tuple[ContextCheckpoint, ...] = ()

    def at_sequence(self, sequence: int) -> ContextFrame:
        for frame in self.frames:
            if frame.source_sequence == sequence:
                return frame
        raise KeyError(f"no context frame for sequence {sequence}")


class ArtifactIndexRecord(ProjectionNode):
    source: NodeSource = "observed"
    status: LifecycleStatus = "completed"
    reference: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    producing_sequence: int | None = Field(default=None, ge=1)
    consuming_sequences: tuple[int, ...] = ()
    turn_id: str | None = None
    step_id: str | None = None
    request_id: str | None = None
    tool_call_id: str | None = None
    result_id: str | None = None
    evidence_id: str | None = None
    claim_id: str | None = None


class ArtifactIndex(StrictFrozenModel):
    analysis_id: str = Field(min_length=1)
    records: Mapping[str, ArtifactIndexRecord] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_records(self) -> "ArtifactIndex":
        object.__setattr__(self, "records", _deep_freeze(self.records))
        return self


class ProjectionDiagnostic(ProjectionNode):
    source: NodeSource = "derived"
    status: LifecycleStatus = "unavailable"
    severity: Literal["info", "warning", "error"]
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProjectedRun(StrictFrozenModel):
    analysis_id: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=1)
    agent: AgentTrajectory
    business: BusinessTrajectory
    context: ContextTimeline
    artifacts: ArtifactIndex
    diagnostics: tuple[ProjectionDiagnostic, ...] = ()


__all__ = [
    "AgentRetry",
    "AgentStep",
    "AgentTrajectory",
    "AgentTurn",
    "ArtifactIndex",
    "ArtifactIndexRecord",
    "AssistantResponse",
    "BusinessNode",
    "BusinessProblem",
    "BusinessTrajectory",
    "ContextCheckpoint",
    "ContextFrame",
    "ContextTimeline",
    "LifecycleStatus",
    "ModelRequest",
    "NodeSource",
    "ProjectedRun",
    "ProjectionDiagnostic",
    "ProjectionNode",
    "ToolCall",
]
