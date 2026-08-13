from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from pydantic import ValidationError

from grid_agent.analysis.models import (
    ActiveTurn,
    AnalysisContext,
    BaselineRecord,
    ContextEventDraft,
    DiagnosticRecord,
    EvidenceRecord,
    InputRecord,
    LimitationRecord,
    ObservationRecord,
    ResultRecord,
    RuntimeRecord,
    TurnRecord,
    VerifiedFact,
)


class ContextTransitionError(RuntimeError):
    """Raised when an analysis context event violates reducer invariants."""


_TERMINAL_STATUSES = {"completed", "failed"}
_SIMULATOR_PROVENANCE = {"simulator", "gridctl"}


def canonical_state_hash(state: AnalysisContext) -> str:
    payload = state.model_dump(mode="json")
    payload.pop("state_hash", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def initial_context(
    analysis_id: str,
    input_payload: dict[str, Any],
    runtime_payload: dict[str, Any],
) -> AnalysisContext:
    state = AnalysisContext(
        analysis_id=analysis_id,
        revision=0,
        state_hash="",
        status="initializing",
        input=InputRecord.model_validate(input_payload),
        runtime=RuntimeRecord.model_validate(runtime_payload),
    )
    return state.model_copy(update={"state_hash": canonical_state_hash(state)})


def reduce_context(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    if state.status in _TERMINAL_STATUSES:
        raise ContextTransitionError("terminal analysis context cannot be mutated")

    try:
        next_state = _apply_transition(state, draft)
    except ValidationError as exc:
        raise ContextTransitionError(str(exc)) from exc

    if next_state is state:
        next_state = state.model_copy()
    next_state = next_state.model_copy(update={"revision": state.revision + 1})
    return next_state.model_copy(update={"state_hash": canonical_state_hash(next_state)})


def _apply_transition(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    if draft.event_type == "analysis.started":
        return state.model_copy(update={"status": "running"})
    if draft.event_type == "turn.started":
        return _start_turn(state, draft)
    if draft.event_type == "simulator.context.opened":
        return _open_simulator_context(state, draft)
    if draft.event_type == "tool.observation.recorded":
        return _record_observation(state, draft)
    if draft.event_type == "result.registered":
        return _register_result(state, draft)
    if draft.event_type == "evidence.registered":
        return _register_evidence(state, draft)
    if draft.event_type == "fact.verified":
        return _record_verified_fact(state, draft)
    if draft.event_type == "tool.failed":
        return _record_diagnostic(state, draft)
    if draft.event_type == "answer.submitted":
        return _record_answer_submission(state, draft)
    if draft.event_type == "audit.diagnostic.recorded":
        return _record_diagnostic(state, draft)
    if draft.event_type == "limitation.recorded":
        return _record_limitation(state, draft)
    if draft.event_type == "limitation.resolved":
        return _resolve_limitation(state, draft)
    if draft.event_type == "turn.completed":
        return _complete_turn(state, draft)
    if draft.event_type == "analysis.completed":
        return _complete_analysis(state, "completed")
    if draft.event_type == "analysis.failed":
        return _complete_analysis(state, "failed")
    raise ContextTransitionError(f"unsupported event type: {draft.event_type}")


def _start_turn(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    if state.current_turn is not None:
        raise ContextTransitionError("active turn already exists")
    if draft.turn_id is None:
        raise ContextTransitionError("turn.started requires turn_id")
    if any(turn.turn_id == draft.turn_id for turn in state.turns):
        raise ContextTransitionError("turn_id was already completed")
    payload = dict(draft.payload)
    payload["turn_id"] = draft.turn_id
    turn = ActiveTurn.model_validate(payload)
    return state.model_copy(update={"status": "running", "current_turn": turn})


def _open_simulator_context(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    _require_active_turn(state, draft)
    baseline = BaselineRecord.model_validate(draft.payload)
    baselines = _upsert_record(
        state.baselines,
        key=baseline.context_ref,
        value=baseline,
        duplicate_message=f"baseline {baseline.context_ref} already exists with different content",
    )
    return state.model_copy(update={"baselines": baselines, "active_context_ref": baseline.context_ref})


def _record_observation(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    turn = _require_active_turn(state, draft)
    capability = _require_capability(draft)
    payload = dict(draft.payload)
    payload["turn_id"] = turn.turn_id
    payload["capability"] = capability
    observation = ObservationRecord.model_validate(payload)
    _require_known_refs(state, observation.consumed_refs, allow_unregistered_context_refs=True)
    if capability == "result.branches.rank" and observation.summary.get("ok") is not False:
        _validate_ranking_observation(state, observation)
    observations = _upsert_record(
        state.observations,
        key=observation.observation_ref,
        value=observation,
        duplicate_message=f"observation {observation.observation_ref} already exists with different content",
    )
    current_turn = _merge_turn_refs(turn, consumed_refs=observation.consumed_refs, produced_refs=observation.produced_refs)
    return state.model_copy(update={"observations": observations, "current_turn": current_turn})


def _record_answer_submission(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    turn = _require_active_turn(state, draft)
    payload = draft.payload
    if payload.get("turn_id") != turn.turn_id:
        raise ContextTransitionError("answer.submitted must bind to active turn")
    for key in ("answer_path", "answer_sha256", "answer_draft_path"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ContextTransitionError(f"answer.submitted requires {key}")
    result_refs = payload.get("result_refs", [])
    claimed_refs = payload.get("claim_evidence_refs", [])
    if not isinstance(result_refs, list) or not all(isinstance(item, str) for item in result_refs):
        raise ContextTransitionError("answer.submitted result_refs must be strings")
    if not isinstance(claimed_refs, list) or not all(isinstance(item, str) for item in claimed_refs):
        raise ContextTransitionError("answer.submitted claim_evidence_refs must be strings")
    # Submission is accepted independently of audit findings; unknown claim
    # references are recorded by the subsequent diagnostic events.
    return state


def _register_result(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    turn = _require_active_turn(state, draft)
    capability = _require_capability(draft)
    if state.active_context_ref is None:
        raise ContextTransitionError("result requires a registered baseline")
    baseline = state.baselines[state.active_context_ref]
    payload = dict(draft.payload)
    payload["turn_id"] = turn.turn_id
    payload["capability"] = capability
    result = ResultRecord.model_validate(payload)
    if result.revision_ref != baseline.revision_ref:
        raise ContextTransitionError("result revision_ref does not match registered baseline")
    results = _upsert_record(
        state.results,
        key=result.result_ref,
        value=result,
        duplicate_message=f"result {result.result_ref} already exists with different content",
    )
    current_turn = _merge_turn_refs(turn, produced_refs=[result.result_ref])
    return state.model_copy(update={"results": results, "current_turn": current_turn})


def _register_evidence(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    payload = dict(draft.payload)
    evidence = EvidenceRecord.model_validate(payload)
    _require_known_refs(state, evidence.refs)
    evidence_by_ref = _upsert_record(
        state.evidence,
        key=evidence.evidence_ref,
        value=evidence,
        duplicate_message=f"evidence {evidence.evidence_ref} already exists with different content",
    )
    current_turn = state.current_turn
    if current_turn is not None and draft.turn_id == current_turn.turn_id:
        current_turn = _merge_turn_refs(current_turn, produced_refs=[evidence.evidence_ref])
    return state.model_copy(update={"evidence": evidence_by_ref, "current_turn": current_turn})


def _record_verified_fact(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    payload = dict(draft.payload)
    authored_by = payload.pop("authored_by", None)
    if authored_by not in _SIMULATOR_PROVENANCE:
        raise ContextTransitionError("fact.verified requires explicit simulator/gridctl provenance")
    capability = _require_capability(draft)
    payload["verifier_capability"] = capability
    fact = VerifiedFact.model_validate(payload)
    if not fact.evidence_refs:
        raise ContextTransitionError("verified facts must come from simulator evidence")
    _require_simulator_evidence_refs(state, fact.evidence_refs)
    facts = _upsert_record(
        state.verified_facts,
        key=fact.fact_ref,
        value=fact,
        duplicate_message=f"verified fact {fact.fact_ref} already exists with different content",
    )
    return state.model_copy(update={"verified_facts": facts})


def _record_diagnostic(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    payload = dict(draft.payload)
    message = payload.pop("message", draft.event_type)
    diagnostic = DiagnosticRecord(
        event_type=draft.event_type,
        turn_id=draft.turn_id,
        capability=draft.capability,
        message=message,
        details=payload,
    )
    return state.model_copy(update={"diagnostics": [*state.diagnostics, diagnostic]})


def _record_limitation(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    payload = dict(draft.payload)
    payload.setdefault("turn_id", draft.turn_id)
    limitation = LimitationRecord.model_validate(payload)
    limitations = _upsert_record(
        {item.limitation_ref: item for item in state.unresolved_limitations},
        key=limitation.limitation_ref,
        value=limitation,
        duplicate_message=f"limitation {limitation.limitation_ref} already exists with different content",
    )
    return state.model_copy(update={"unresolved_limitations": list(limitations.values())})


def _resolve_limitation(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    limitation_ref = draft.payload.get("limitation_ref")
    if not isinstance(limitation_ref, str):
        raise ContextTransitionError("limitation.resolved requires limitation_ref")
    unresolved = [item for item in state.unresolved_limitations if item.limitation_ref != limitation_ref]
    if len(unresolved) == len(state.unresolved_limitations):
        raise ContextTransitionError(f"unknown limitation: {limitation_ref}")
    return state.model_copy(update={"unresolved_limitations": unresolved})


def _complete_turn(state: AnalysisContext, draft: ContextEventDraft) -> AnalysisContext:
    turn = _require_active_turn(state, draft)
    if any(completed_turn.turn_id == turn.turn_id for completed_turn in state.turns):
        raise ContextTransitionError("turn_id was already completed")
    payload = dict(draft.payload)
    consumed_refs = _dedupe([*turn.consumed_refs, *payload.pop("consumed_refs", [])])
    produced_refs = _dedupe([*turn.produced_refs, *payload.pop("produced_refs", [])])
    _require_known_refs(state, consumed_refs)
    turn_record = TurnRecord(
        turn_id=turn.turn_id,
        ordinal=turn.ordinal,
        instruction=turn.instruction,
        instruction_sha256=turn.instruction_sha256,
        nonce_sha256=turn.nonce_sha256,
        consumed_refs=consumed_refs,
        produced_refs=produced_refs,
        **payload,
    )
    return state.model_copy(update={"current_turn": None, "turns": [*state.turns, turn_record]})


def _complete_analysis(state: AnalysisContext, status: str) -> AnalysisContext:
    if state.current_turn is not None:
        raise ContextTransitionError("cannot complete analysis with an active turn")
    return state.model_copy(update={"status": status})


def _require_active_turn(state: AnalysisContext, draft: ContextEventDraft) -> ActiveTurn:
    if state.current_turn is None:
        raise ContextTransitionError("event requires an active turn")
    if draft.turn_id != state.current_turn.turn_id:
        raise ContextTransitionError("event turn_id does not match active turn")
    return state.current_turn


def _optional_matching_turn(state: AnalysisContext, draft: ContextEventDraft) -> ActiveTurn | None:
    if state.current_turn is None:
        return None
    if draft.turn_id != state.current_turn.turn_id:
        raise ContextTransitionError("event turn_id does not match active turn")
    return state.current_turn


def _require_capability(draft: ContextEventDraft) -> str:
    if not draft.capability:
        raise ContextTransitionError(f"{draft.event_type} requires capability")
    return draft.capability


def _require_known_refs(
    state: AnalysisContext,
    refs: list[str],
    *,
    allow_unregistered_context_refs: bool = False,
) -> None:
    known_refs = set(state.baselines) | set(state.results) | set(state.evidence) | set(state.verified_facts)
    if state.active_context_ref is not None:
        known_refs.add(state.active_context_ref)
    unknown = [
        ref
        for ref in refs
        if ref not in known_refs and not (allow_unregistered_context_refs and ref.startswith("context:sha256:"))
    ]
    if unknown:
        raise ContextTransitionError(f"unknown referenced context artifact: {unknown[0]}")


def _require_simulator_evidence_refs(state: AnalysisContext, refs: list[str]) -> None:
    unknown = [ref for ref in refs if ref not in state.evidence]
    if unknown:
        raise ContextTransitionError(f"verified fact references unknown simulator evidence: {unknown[0]}")
    unsupported = [ref for ref in refs if not _has_simulator_provenance(state.evidence[ref])]
    if unsupported:
        raise ContextTransitionError(f"evidence provenance is not simulator/gridctl: {unsupported[0]}")


def _has_simulator_provenance(evidence: EvidenceRecord) -> bool:
    summary_provenance = evidence.summary.get("provenance")
    return evidence.kind in _SIMULATOR_PROVENANCE or summary_provenance in _SIMULATOR_PROVENANCE


def _validate_ranking_observation(state: AnalysisContext, observation: ObservationRecord) -> None:
    if observation.produced_refs:
        raise ContextTransitionError("result.branches.rank observations must not produce refs")
    if not any(ref in state.results for ref in observation.consumed_refs):
        raise ContextTransitionError("result.branches.rank must consume a preexisting result ref")


def _merge_turn_refs(
    turn: ActiveTurn,
    *,
    consumed_refs: list[str] | None = None,
    produced_refs: list[str] | None = None,
) -> ActiveTurn:
    return turn.model_copy(
        update={
            "consumed_refs": _dedupe([*turn.consumed_refs, *(consumed_refs or [])]),
            "produced_refs": _dedupe([*turn.produced_refs, *(produced_refs or [])]),
        }
    )


def _upsert_record[T](
    records: dict[str, T],
    *,
    key: str,
    value: T,
    duplicate_message: str,
) -> dict[str, T]:
    existing = records.get(key)
    if existing is not None:
        if existing != value:
            raise ContextTransitionError(duplicate_message)
        return records
    return {**records, key: value}


def _dedupe(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)
    return deduped
