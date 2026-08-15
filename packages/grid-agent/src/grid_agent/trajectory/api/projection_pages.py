"""Bounded public pages for operational trajectory projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from fastapi.exceptions import RequestValidationError
from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from grid_agent.trajectory.api.cursor import (
    CursorCodec,
    CursorExpectation,
    CursorState,
)
from grid_agent.trajectory.api.paging import ProjectionPager
from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import StrictFrozenModel
from grid_agent.trajectory.projection_models import (
    AgentEventRow,
    AgentRetry,
    AgentStep,
    AgentTurn,
    ArtifactIndexRecord,
    AssistantResponse,
    ContextFrameSummary,
    LifecycleStatus,
    ModelRequest,
    NodeSource,
    ProjectedRun,
    ToolCall,
)


ProjectionView = Literal["agent", "context", "evidence"]
AgentEventKind = Literal["turn", "step", "request", "retry", "response", "tool"]
EvidenceSort = Literal["producer_sequence", "verification_status"]

_PROJECTION_VERSIONS: dict[ProjectionView, str] = {
    "agent": "agent-event-rows/1.0",
    "context": "context-frame-summaries/1.0",
    "evidence": "evidence-records/1.0",
}
_PUBLIC_TOOL_CAPABILITIES = frozenset(
    {
        "analysis.contingency.n_minus_one.run",
        "analysis.powerflow.ac.run",
        "context.get",
        "context.open",
        "environment.describe",
        "evidence.get",
        "grid_analysis_contingency_n_minus_one",
        "grid_analysis_powerflow_ac",
        "grid_context_get",
        "grid_context_open",
        "grid_environment_describe",
        "grid_evidence_get",
        "grid_guide_open",
        "grid_model_constraints_describe",
        "grid_model_dataset_describe",
        "grid_model_dataset_query",
        "grid_model_element_get",
        "grid_model_list",
        "grid_record_decision",
        "grid_result_branches_rank",
        "grid_submit_answer",
        "grid_topology_branch_endpoints",
        "grid_topology_components_get",
        "gridctl",
        "model.constraints.describe",
        "model.dataset.describe",
        "model.dataset.query",
        "model.element.get",
        "model.list",
        "result.branches.rank",
        "topology.branch.endpoints.get",
        "topology.components.get",
    }
)


class ProjectionPageResponse(StrictFrozenModel):
    """The stable, byte- and record-bounded projection page envelope."""

    analysis_id: str = Field(min_length=1)
    items: tuple[dict[str, Any], ...] = ()
    older_cursor: str | None = None
    newer_cursor: None = None
    first_sequence: int | None = Field(default=None, ge=1)
    last_sequence: int | None = Field(default=None, ge=1)
    has_older: bool
    encoded_bytes: int = Field(ge=0)


class _FilterModel(StrictFrozenModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _AgentFilters(_FilterModel):
    turn_id: str | None = Field(default=None, min_length=1, max_length=500)
    kind: AgentEventKind | None = None
    status: LifecycleStatus | None = None
    capability: str | None = Field(default=None, min_length=1, max_length=500)
    q: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("q")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("q must contain visible text")
        return normalized


class _ContextFilters(_FilterModel):
    from_sequence: int | None = Field(default=None, ge=1)
    to_sequence: int | None = Field(default=None, ge=1)
    from_revision: int | None = Field(default=None, ge=0)
    to_revision: int | None = Field(default=None, ge=0)
    changed: bool | None = None
    request_input: bool | None = None

    @model_validator(mode="after")
    def require_ordered_ranges(self) -> "_ContextFilters":
        if (
            self.from_sequence is not None
            and self.to_sequence is not None
            and self.from_sequence > self.to_sequence
        ):
            raise ValueError("from_sequence must not exceed to_sequence")
        if (
            self.from_revision is not None
            and self.to_revision is not None
            and self.from_revision > self.to_revision
        ):
            raise ValueError("from_revision must not exceed to_revision")
        return self


class _EvidenceFilters(_FilterModel):
    kind: str | None = Field(default=None, min_length=1, max_length=100)
    source: NodeSource | None = None
    verification_status: Literal["verified", "unavailable"] | None = None
    from_sequence: int | None = Field(default=None, ge=1)
    to_sequence: int | None = Field(default=None, ge=1)
    relevant_ref: str | None = Field(default=None, min_length=1, max_length=1_000)
    sort: EvidenceSort | None = None

    @model_validator(mode="after")
    def require_ordered_range(self) -> "_EvidenceFilters":
        if (
            self.from_sequence is not None
            and self.to_sequence is not None
            and self.from_sequence > self.to_sequence
        ):
            raise ValueError("from_sequence must not exceed to_sequence")
        return self


@dataclass(slots=True)
class _ProjectionRecord:
    sequence: int
    item: dict[str, Any]

    def model_dump(self, *, mode: str) -> object:
        del mode
        return self.item


@dataclass(frozen=True, slots=True)
class _AgentCandidate:
    row: AgentEventRow
    capability: str | None = None


def projection_page(
    projected: ProjectedRun,
    view: ProjectionView,
    cursor: str | None,
    filters: Mapping[str, str | int | bool | None],
    codec: CursorCodec,
) -> ProjectionPageResponse:
    """Return one signed, filter-bound page of public projection metadata."""
    normalized_filters = _normalize_filters(view, filters)
    filter_fingerprint = sha256(
        canonical_json_bytes(normalized_filters)
    ).hexdigest()
    source_fingerprint = f"{projected.source_fingerprint}:{filter_fingerprint}"
    expectation = CursorExpectation(
        analysis_id=projected.analysis_id,
        view=view,
        source_fingerprint=source_fingerprint,
        projection_version=_PROJECTION_VERSIONS[view],
    )
    cursor_state = codec.decode(cursor, expectation) if cursor else None
    records = _records_for(projected, view, normalized_filters)
    page = ProjectionPager().page(records, cursor_state=cursor_state)
    first_sequence, last_sequence = _public_sequence_bounds(
        view, page.items, page.first_sequence, page.last_sequence
    )
    older_cursor = (
        codec.encode(
            CursorState(
                analysis_id=projected.analysis_id,
                view=view,
                source_fingerprint=source_fingerprint,
                projection_version=_PROJECTION_VERSIONS[view],
                before_sequence=page.older_cursor,
            )
        )
        if page.older_cursor is not None
        else None
    )
    return ProjectionPageResponse(
        analysis_id=projected.analysis_id,
        items=tuple(record.item for record in page.items),
        older_cursor=older_cursor,
        newer_cursor=page.newer_cursor,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
        has_older=page.has_older,
        encoded_bytes=page.encoded_bytes,
    )


def _normalize_filters(
    view: ProjectionView,
    filters: Mapping[str, str | int | bool | None],
) -> dict[str, str | int | bool]:
    model_type: type[_FilterModel]
    if view == "agent":
        model_type = _AgentFilters
    elif view == "context":
        model_type = _ContextFilters
    else:
        model_type = _EvidenceFilters
    try:
        validated = model_type.model_validate(dict(filters))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    normalized = validated.model_dump(mode="json", exclude_none=True)
    if view == "evidence":
        normalized.setdefault("sort", "producer_sequence")
    return normalized


def _public_sequence_bounds(
    view: ProjectionView,
    records: tuple[_ProjectionRecord, ...],
    first_sequence: int | None,
    last_sequence: int | None,
) -> tuple[int | None, int | None]:
    if view != "evidence":
        return first_sequence, last_sequence
    source_sequences = tuple(
        sequence
        for record in records
        for sequence in record.item.get("source_sequences", ())
        if isinstance(sequence, int)
        and not isinstance(sequence, bool)
        and sequence >= 1
    )
    if not source_sequences:
        return first_sequence, last_sequence
    return min(source_sequences), max(source_sequences)


def _records_for(
    projected: ProjectedRun,
    view: ProjectionView,
    filters: Mapping[str, str | int | bool],
) -> tuple[_ProjectionRecord, ...]:
    if view == "agent":
        return _agent_records(projected, filters)
    if view == "context":
        return _context_records(projected, filters)
    return _evidence_records(projected, filters)


def _agent_records(
    projected: ProjectedRun,
    filters: Mapping[str, str | int | bool],
) -> tuple[_ProjectionRecord, ...]:
    candidates = tuple(
        candidate
        for candidate in _agent_candidates(projected)
        if _agent_matches(candidate, filters)
    )
    return tuple(
        _ProjectionRecord(
            sequence=candidate.row.source_sequence,
            item=candidate.row.model_dump(mode="json"),
        )
        for candidate in candidates
    )


def _agent_candidates(projected: ProjectedRun) -> tuple[_AgentCandidate, ...]:
    candidates: list[_AgentCandidate] = []
    for turn in projected.agent.turns:
        candidates.append(_AgentCandidate(_turn_row(turn)))
        for step in turn.steps:
            candidates.append(_AgentCandidate(_step_row(turn, step)))
            request = step.request
            if request is None:
                continue
            candidates.append(_AgentCandidate(_request_row(turn, step, request)))
            candidates.extend(
                _AgentCandidate(_retry_row(turn, request, retry))
                for retry in request.retries
            )
            candidates.extend(
                _AgentCandidate(
                    _tool_row(turn, request, tool), capability=tool.capability
                )
                for tool in request.tools
            )
            if request.response is not None:
                candidates.append(
                    _AgentCandidate(_response_row(turn, request, request.response))
                )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (candidate.row.source_sequence, candidate.row.id),
        )
    )


def _turn_row(turn: AgentTurn) -> AgentEventRow:
    title = f"Turn {turn.ordinal}" if turn.ordinal is not None else "Turn"
    return _agent_row(turn, None, turn.turn_id, "turn", 1, title)


def _step_row(turn: AgentTurn, step: AgentStep) -> AgentEventRow:
    return _agent_row(
        step,
        turn.id,
        turn.turn_id,
        "step",
        2,
        f"Step {step.step_id}",
    )


def _request_row(
    turn: AgentTurn, step: AgentStep, request: ModelRequest
) -> AgentEventRow:
    return _agent_row(
        request,
        step.id,
        turn.turn_id,
        "request",
        3,
        f"Request {request.request_id}",
    )


def _retry_row(
    turn: AgentTurn, request: ModelRequest, retry: AgentRetry
) -> AgentEventRow:
    delay = (
        f"Delay {retry.delay_seconds:g} seconds"
        if retry.delay_seconds is not None
        else None
    )
    return _agent_row(
        retry,
        request.id,
        turn.turn_id,
        "retry",
        4,
        f"Retry {retry.attempt} of {retry.max_attempts}",
        detail=delay,
    )


def _response_row(
    turn: AgentTurn, request: ModelRequest, response: AssistantResponse
) -> AgentEventRow:
    facts: list[str] = []
    if response.input_tokens is not None:
        facts.append(f"{response.input_tokens} input tokens")
    if response.output_tokens is not None:
        facts.append(f"{response.output_tokens} output tokens")
    if response.duration_seconds is not None:
        facts.append(f"{response.duration_seconds:g} seconds")
    return _agent_row(
        response,
        request.id,
        turn.turn_id,
        "response",
        4,
        "Assistant response",
        detail=" · ".join(facts) or None,
    )


def _tool_row(
    turn: AgentTurn, request: ModelRequest, tool: ToolCall
) -> AgentEventRow:
    return _agent_row(
        tool,
        request.id,
        turn.turn_id,
        "tool",
        4,
        (
            _bounded_public_text(tool.capability, fallback="Tool")
            if tool.capability in _PUBLIC_TOOL_CAPABILITIES
            else "Tool"
        ),
    )


def _agent_row(
    node: AgentTurn | AgentStep | ModelRequest | AgentRetry | AssistantResponse | ToolCall,
    parent_id: str | None,
    turn_id: str,
    kind: AgentEventKind,
    level: int,
    title: str,
    *,
    detail: str | None = None,
) -> AgentEventRow:
    return AgentEventRow(
        id=node.id,
        parent_id=parent_id,
        turn_id=turn_id,
        kind=kind,
        level=level,
        source_sequence=min(node.source_sequences),
        source=node.source,
        status=node.status,
        title=_bounded_public_text(title, fallback=kind.title()),
        detail=(
            _bounded_public_text(detail, fallback="", maximum=1_000)
            if detail
            else None
        ),
    )


def _bounded_public_text(
    value: str, *, fallback: str, maximum: int = 500
) -> str:
    normalized = " ".join(value.split())
    return (normalized or fallback)[:maximum]


def _agent_matches(
    candidate: _AgentCandidate,
    filters: Mapping[str, str | int | bool],
) -> bool:
    row = candidate.row
    if filters.get("turn_id") != row.turn_id and "turn_id" in filters:
        return False
    if filters.get("kind") != row.kind and "kind" in filters:
        return False
    if filters.get("status") != row.status and "status" in filters:
        return False
    if "capability" in filters and filters["capability"] != candidate.capability:
        return False
    query = filters.get("q")
    if isinstance(query, str):
        haystack = " ".join(
            (
                row.id,
                row.turn_id,
                row.kind,
                row.status,
                row.title,
                row.detail or "",
                candidate.capability or "",
            )
        ).casefold()
        if query not in haystack:
            return False
    return True


def _context_records(
    projected: ProjectedRun,
    filters: Mapping[str, str | int | bool],
) -> tuple[_ProjectionRecord, ...]:
    summaries = tuple(
        summary
        for summary in (
            ContextFrameSummary(
                id=frame.id,
                source_sequence=frame.source_sequence,
                before_revision=frame.before_revision,
                after_revision=frame.after_revision,
                changed=frame.before_state_hash != frame.after_state_hash,
                request_input_available=frame.request_artifact_ref is not None,
                event_kind="context-frame",
            )
            for frame in projected.context.frames
        )
        if _context_matches(summary, filters)
    )
    return tuple(
        _ProjectionRecord(
            sequence=summary.source_sequence,
            item=summary.model_dump(mode="json"),
        )
        for summary in summaries
    )


def _context_matches(
    summary: ContextFrameSummary,
    filters: Mapping[str, str | int | bool],
) -> bool:
    from_sequence = filters.get("from_sequence")
    if isinstance(from_sequence, int) and summary.source_sequence < from_sequence:
        return False
    to_sequence = filters.get("to_sequence")
    if isinstance(to_sequence, int) and summary.source_sequence > to_sequence:
        return False
    from_revision = filters.get("from_revision")
    if isinstance(from_revision, int) and summary.after_revision < from_revision:
        return False
    to_revision = filters.get("to_revision")
    if isinstance(to_revision, int) and summary.before_revision > to_revision:
        return False
    if "changed" in filters and filters["changed"] is not summary.changed:
        return False
    if (
        "request_input" in filters
        and filters["request_input"] is not summary.request_input_available
    ):
        return False
    return True


def _evidence_records(
    projected: ProjectedRun,
    filters: Mapping[str, str | int | bool],
) -> tuple[_ProjectionRecord, ...]:
    selected = tuple(
        record
        for record in projected.artifacts.records.values()
        if _evidence_matches(record, filters)
    )
    sort = filters.get("sort", "producer_sequence")
    ordered = tuple(sorted(selected, key=lambda record: _evidence_sort_key(record, sort)))
    # Evidence may contain several references produced by one event.  The signed
    # cursor therefore uses this deterministic filtered order as its unique
    # boundary while each item retains its exact producer/consumer sequences.
    return tuple(
        _ProjectionRecord(sequence=position, item=record.model_dump(mode="json"))
        for position, record in enumerate(ordered, start=1)
    )


def _evidence_matches(
    record: ArtifactIndexRecord,
    filters: Mapping[str, str | int | bool],
) -> bool:
    if "kind" in filters and filters["kind"] != record.kind:
        return False
    if "source" in filters and filters["source"] != record.source:
        return False
    if (
        "verification_status" in filters
        and filters["verification_status"] != record.verification_status
    ):
        return False
    from_sequence = filters.get("from_sequence")
    to_sequence = filters.get("to_sequence")
    if isinstance(from_sequence, int) or isinstance(to_sequence, int):
        relevant_sequences = set(record.source_sequences)
        if record.producing_sequence is not None:
            relevant_sequences.add(record.producing_sequence)
        relevant_sequences.update(record.consuming_sequences)
        if not any(
            (not isinstance(from_sequence, int) or sequence >= from_sequence)
            and (not isinstance(to_sequence, int) or sequence <= to_sequence)
            for sequence in relevant_sequences
        ):
            return False
    relevant_ref = filters.get("relevant_ref")
    if isinstance(relevant_ref, str) and relevant_ref not in _evidence_relations(record):
        return False
    return True


def _evidence_relations(record: ArtifactIndexRecord) -> set[str]:
    values = {
        record.id,
        record.reference,
        record.turn_id,
        record.step_id,
        record.request_id,
        record.tool_call_id,
        record.result_id,
        record.evidence_id,
        record.claim_id,
    }
    return {value for value in values if value is not None}


def _evidence_sort_key(
    record: ArtifactIndexRecord, sort: str | int | bool
) -> tuple[object, ...]:
    producer = record.producing_sequence
    effective_sequence = producer if producer is not None else min(record.source_sequences)
    if sort == "verification_status":
        return (record.verification_status, effective_sequence, record.reference)
    return (effective_sequence, record.reference)


__all__ = ["ProjectionPageResponse", "projection_page"]
