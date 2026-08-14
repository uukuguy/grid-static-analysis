"""Typed, hash-chained native run events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grid_agent.trajectory.canonical import canonical_json_bytes, sha256_ref


class StrictFrozenModel(BaseModel):
    """Immutable protocol model which rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EmptyPayload(StrictFrozenModel):
    pass


class AnalysisTerminalPayload(StrictFrozenModel):
    completed_turns: int = Field(ge=0)
    total_turns: int = Field(ge=0)


class ErrorPayload(StrictFrozenModel):
    error_type: str
    message: str


class TurnStartedPayload(StrictFrozenModel):
    ordinal: int = Field(ge=1)
    instruction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TurnTerminalPayload(StrictFrozenModel):
    status: Literal["success", "failed"]
    duration_seconds: float | None = Field(default=None, ge=0)


class ModelRequestPayload(StrictFrozenModel):
    artifact_ref: str
    request_index: int = Field(ge=1)


class ModelResponsePayload(StrictFrozenModel):
    artifact_ref: str
    stop_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    ttft_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)


class RetryPayload(StrictFrozenModel):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    delay_seconds: float | None = Field(default=None, ge=0)
    message: str | None = None


class ToolPayload(StrictFrozenModel):
    capability: str
    artifact_ref: str | None = None
    ok: bool | None = None


class DecisionPayload(StrictFrozenModel):
    intent: str = Field(min_length=1, max_length=500)
    decision: str = Field(min_length=1, max_length=500)
    next_action: str = Field(min_length=1, max_length=500)


class ClaimPayload(StrictFrozenModel):
    submission_id: str
    statement: str = Field(min_length=1, max_length=1000)
    category: Literal[
        "topology",
        "constraint",
        "numerical_result",
        "risk_judgment",
        "offline_information",
    ]
    result_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class ContextPayload(StrictFrozenModel):
    revision: int = Field(ge=0)
    state_hash: str
    artifact_ref: str | None = None


class AnswerPayload(StrictFrozenModel):
    submission_id: str
    artifact_ref: str
    result_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class DiagnosticPayload(StrictFrozenModel):
    severity: Literal["info", "warning", "error"]
    category: str
    message: str


PAYLOAD_MODELS: dict[str, type[StrictFrozenModel]] = {
    "analysis.started": EmptyPayload,
    "analysis.completed": AnalysisTerminalPayload,
    "analysis.failed": ErrorPayload,
    "turn.started": TurnStartedPayload,
    "turn.completed": TurnTerminalPayload,
    "turn.failed": ErrorPayload,
    "step.started": EmptyPayload,
    "step.completed": EmptyPayload,
    "step.failed": ErrorPayload,
    "model.request.started": ModelRequestPayload,
    "model.response.completed": ModelResponsePayload,
    "model.response.failed": ErrorPayload,
    "model.retry.scheduled": RetryPayload,
    "model.retry.started": RetryPayload,
    "model.retry.exhausted": RetryPayload,
    "tool.started": ToolPayload,
    "tool.completed": ToolPayload,
    "tool.failed": ToolPayload,
    "business.decision.declared": DecisionPayload,
    "business.claim.declared": ClaimPayload,
    "context.projected": ContextPayload,
    "context.injected": ContextPayload,
    "answer.submitted": AnswerPayload,
    "answer.rejected": ErrorPayload,
    "audit.diagnostic.recorded": DiagnosticPayload,
}

EventType = Literal[
    "analysis.started",
    "analysis.completed",
    "analysis.failed",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "step.started",
    "step.completed",
    "step.failed",
    "model.request.started",
    "model.response.completed",
    "model.response.failed",
    "model.retry.scheduled",
    "model.retry.started",
    "model.retry.exhausted",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "business.decision.declared",
    "business.claim.declared",
    "context.projected",
    "context.injected",
    "answer.submitted",
    "answer.rejected",
    "audit.diagnostic.recorded",
]


class RunScope(StrictFrozenModel):
    turn_id: str | None = Field(default=None, min_length=1)
    step_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)
    tool_call_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_nested_identifiers(self) -> "RunScope":
        if self.step_id is not None and self.turn_id is None:
            raise ValueError("step_id requires turn_id")
        if self.request_id is not None and self.step_id is None:
            raise ValueError("request_id requires step_id")
        if self.tool_call_id is not None and self.request_id is None:
            raise ValueError("tool_call_id requires request_id")
        return self


class Causation(StrictFrozenModel):
    parent_sequence: int | None = Field(default=None, ge=1)
    correlation_id: str | None = Field(default=None, min_length=1)


class EventSource(StrictFrozenModel):
    kind: Literal["observed", "agent-declared"] = "observed"
    producer: str = Field(default="grid-agent", min_length=1)
    integrity: str = Field(default="verified", min_length=1)


class ContextBoundary(StrictFrozenModel):
    before_revision: int | None = Field(default=None, ge=0)
    after_revision: int | None = Field(default=None, ge=0)


class EventRefs(StrictFrozenModel):
    consumed: tuple[str, ...] = ()
    produced: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def reject_empty_references(self) -> "EventRefs":
        if any(not reference for references in (self.consumed, self.produced, self.evidence) for reference in references):
            raise ValueError("event references must not be empty")
        return self


class EventDraft(StrictFrozenModel):
    event_type: EventType
    scope: RunScope = Field(default_factory=RunScope)
    causation: Causation = Field(default_factory=Causation)
    source: EventSource = Field(default_factory=EventSource)
    context: ContextBoundary = Field(default_factory=ContextBoundary)
    refs: EventRefs = Field(default_factory=EventRefs)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_closed_payload(self) -> "EventDraft":
        payload_model = PAYLOAD_MODELS[self.event_type]
        payload = payload_model.model_validate(self.payload).model_dump(mode="json")
        object.__setattr__(self, "payload", payload)
        return self


class RunEvent(EventDraft):
    schema_version: Literal["grid-run-event/1.0"] = "grid-run-event/1.0"
    analysis_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    timestamp: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
    )
    previous_event_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def build_event(
    draft: EventDraft,
    *,
    analysis_id: str,
    sequence: int,
    timestamp: datetime,
    previous_event_hash: str,
) -> RunEvent:
    """Build a validated native event and its canonical content hash."""
    timestamp_utc = timestamp.astimezone(UTC)
    event_without_hash = {
        "schema_version": "grid-run-event/1.0",
        "analysis_id": analysis_id,
        "sequence": sequence,
        "timestamp": timestamp_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "event_type": draft.event_type,
        "previous_event_hash": previous_event_hash,
        "scope": draft.scope.model_dump(mode="json"),
        "causation": draft.causation.model_dump(mode="json"),
        "source": draft.source.model_dump(mode="json"),
        "context": draft.context.model_dump(mode="json"),
        "refs": draft.refs.model_dump(mode="json"),
        "payload": draft.payload,
    }
    return RunEvent.model_validate(
        {
            **event_without_hash,
            "event_hash": sha256_ref(canonical_json_bytes(event_without_hash)),
        }
    )
