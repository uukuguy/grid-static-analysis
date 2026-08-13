from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EventType = Literal[
    "analysis.started",
    "turn.started",
    "simulator.context.opened",
    "tool.observation.recorded",
    "result.registered",
    "evidence.registered",
    "fact.verified",
    "tool.failed",
    "answer.submitted",
    "audit.diagnostic.recorded",
    "limitation.recorded",
    "limitation.resolved",
    "turn.completed",
    "analysis.completed",
    "analysis.failed",
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextEventDraft(StrictFrozenModel):
    event_type: EventType
    turn_id: str | None = None
    capability: str | None = None
    trace_sequence: int | None = None
    timestamp: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisContextEvent(ContextEventDraft):
    schema_version: Literal["analysis-context-event/1.0"] = "analysis-context-event/1.0"
    analysis_id: str
    sequence: int
    previous_revision: int
    previous_state_hash: str
    next_revision: int
    next_state_hash: str
    integrity: Literal["verified", "diagnostic"]


class InputRecord(StrictFrozenModel):
    copied_path: str
    source_path: str
    sha256: str
    instruction_count: int


class RuntimeRecord(StrictFrozenModel):
    provider: str
    model: str
    grid_capability_protocol: str
    pandapower_version: str


class ActiveTurn(StrictFrozenModel):
    turn_id: str
    ordinal: int
    instruction: str
    instruction_sha256: str
    nonce_sha256: str
    consumed_refs: list[str] = Field(default_factory=list)
    produced_refs: list[str] = Field(default_factory=list)


class TurnRecord(StrictFrozenModel):
    turn_id: str
    ordinal: int
    instruction: str
    instruction_sha256: str
    nonce_sha256: str
    status: Literal["success", "failed"]
    answer_path: str | None = None
    answer_sha256: str | None = None
    duration_seconds: float | None = None
    consumed_refs: list[str] = Field(default_factory=list)
    produced_refs: list[str] = Field(default_factory=list)


class BaselineRecord(StrictFrozenModel):
    context_ref: str
    revision_ref: str
    path: str
    source: dict[str, Any]
    network: dict[str, Any]


class ObservationRecord(StrictFrozenModel):
    observation_ref: str
    turn_id: str
    capability: str
    path: str
    summary: dict[str, Any] = Field(default_factory=dict)
    producer_observation: dict[str, Any] = Field(default_factory=dict)
    consumed_refs: list[str] = Field(default_factory=list)
    produced_refs: list[str] = Field(default_factory=list)


class ResultRecord(StrictFrozenModel):
    result_ref: str
    turn_id: str
    capability: str
    revision_ref: str
    path: str
    evidence_refs: list[str] = Field(default_factory=list)
    solver_summary: dict[str, Any]
    producer_observation: dict[str, Any]


class EvidenceRecord(StrictFrozenModel):
    evidence_ref: str
    turn_id: str | None = None
    capability: str | None = None
    path: str
    kind: str
    refs: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class VerifiedFact(StrictFrozenModel):
    fact_ref: str
    statement: str
    evidence_refs: list[str]
    verifier_capability: str


class DiagnosticRecord(StrictFrozenModel):
    event_type: str
    turn_id: str | None = None
    capability: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class LimitationRecord(StrictFrozenModel):
    limitation_ref: str
    turn_id: str | None = None
    message: str
    refs: list[str] = Field(default_factory=list)


class AnalysisContext(StrictFrozenModel):
    schema_version: Literal["analysis-context/1.0"] = "analysis-context/1.0"
    analysis_id: str
    revision: int
    state_hash: str
    status: Literal["initializing", "running", "completed", "failed"]
    input: InputRecord
    runtime: RuntimeRecord
    baselines: dict[str, BaselineRecord] = Field(default_factory=dict)
    active_context_ref: str | None = None
    current_turn: ActiveTurn | None = None
    turns: list[TurnRecord] = Field(default_factory=list)
    observations: dict[str, ObservationRecord] = Field(default_factory=dict)
    results: dict[str, ResultRecord] = Field(default_factory=dict)
    evidence: dict[str, EvidenceRecord] = Field(default_factory=dict)
    verified_facts: dict[str, VerifiedFact] = Field(default_factory=dict)
    diagnostics: list[DiagnosticRecord] = Field(default_factory=list)
    unresolved_limitations: list[LimitationRecord] = Field(default_factory=list)
