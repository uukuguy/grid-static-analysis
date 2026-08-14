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
    "domain.state.projected",
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


class CapabilityState(StrictFrozenModel):
    id: str
    availability: Literal["published", "not_published", "not_applicable", "unavailable", "failed"]
    reason: str


class RuntimeRecord(StrictFrozenModel):
    provider: str
    model: str
    grid_capability_protocol: str
    pandapower_version: str
    capability_families: list[CapabilityState] = Field(default_factory=list)


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


class ActiveModelState(StrictFrozenModel):
    context_ref: str
    revision_ref: str
    model_id: str
    source: str
    counts: dict[str, int] = Field(default_factory=dict)


class OperatingState(StrictFrozenModel):
    context_ref: str
    revision_ref: str
    scenario_ref: str | None = None
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    producer_capability: str
    producer_turn_id: str


class ConstraintState(StrictFrozenModel):
    constraint_ref: str
    context_ref: str
    revision_ref: str
    quantity: str
    subject_kind: str
    lower: float | None = None
    upper: float | None = None
    unit: str
    applies_to_count: int
    source_kind: Literal["model", "user", "standard", "task"]
    source_ref: str
    source: dict[str, Any] = Field(default_factory=dict)
    producer_capability: str
    producer_turn_id: str


class ScenarioState(StrictFrozenModel):
    scenario_ref: str
    context_ref: str
    revision_ref: str
    parent_scenario_ref: str | None = None
    kind: str
    status: str
    changes: dict[str, Any] = Field(default_factory=dict)
    result_refs: list[str] = Field(default_factory=list)
    producer_capability: str
    producer_turn_id: str


class CalculationState(StrictFrozenModel):
    result_ref: str
    kind: str
    context_ref: str
    revision_ref: str
    scenario_refs: list[str] = Field(default_factory=list)
    status: str
    solver: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str
    evidence_refs: list[str] = Field(default_factory=list)
    producer_capability: str
    producer_turn_id: str


class ArtifactState(StrictFrozenModel):
    artifact_ref: str
    kind: str
    path: str
    context_ref: str | None = None
    revision_ref: str | None = None
    producer_capability: str
    producer_turn_id: str


class DomainState(StrictFrozenModel):
    model: ActiveModelState | None = None
    operating_state: OperatingState | None = None
    constraints: dict[str, ConstraintState] = Field(default_factory=dict)
    scenarios: dict[str, ScenarioState] = Field(default_factory=dict)
    calculations: dict[str, CalculationState] = Field(default_factory=dict)
    capabilities: dict[str, CapabilityState] = Field(default_factory=dict)
    artifacts: dict[str, ArtifactState] = Field(default_factory=dict)


class DomainStateDelta(StrictFrozenModel):
    projector: str
    model: ActiveModelState | None = None
    operating_state: OperatingState | None = None
    constraints: list[ConstraintState] = Field(default_factory=list)
    scenarios: list[ScenarioState] = Field(default_factory=list)
    calculations: list[CalculationState] = Field(default_factory=list)
    capabilities: list[CapabilityState] = Field(default_factory=list)
    artifacts: list[ArtifactState] = Field(default_factory=list)


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
    domain_state: DomainState = Field(default_factory=DomainState)
