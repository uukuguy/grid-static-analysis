from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from grid_agent.analysis.models import AnalysisContext, VerifiedFact


CONTEXT_VIEW_VERSION = "analysis-context-view/1.0"
MAX_VIEW_BYTES = 64_000
MAX_FACTS_PER_PREDICATE = 20
MAX_DOMAIN_RECORDS = 20
MAX_TEXT_CHARS = 2_000

_LARGE_FIELD_NAMES = frozenset(
    {
        "branch_results",
        "bus_results",
        "line_results",
        "trafo_results",
        "res_bus",
        "res_line",
        "res_trafo",
        "scenarios",
    }
)


class ContextViewTooLarge(RuntimeError):
    """Legacy exception retained for callers; bounded views no longer raise it."""


def build_context_view(context: AnalysisContext) -> dict[str, Any]:
    view: dict[str, Any] = {
        "schema_version": CONTEXT_VIEW_VERSION,
        "analysis_id": context.analysis_id,
        "revision": context.revision,
        "state_hash": context.state_hash,
        "status": context.status,
        "active_baseline": _active_baseline(context),
        "active_model": _active_model(context),
        "capability_status": _capability_status(context),
        "constraints": _constraints(context),
        "reusable_calculations": _reusable_calculations(context),
        "scenarios": _scenarios(context),
        "current_turn": _current_turn(context),
        "completed_turns": _completed_turns(context),
        "reusable_results": _reusable_results(context),
        "verified_facts": _verified_facts(context),
        "unresolved_limitations": _unresolved_limitations(context),
    }
    return _fit_within_budget(view)


def materialize_context_view(context: AnalysisContext, path: Path) -> None:
    view = build_context_view(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(view) + "\n", encoding="utf-8")


def _active_baseline(context: AnalysisContext) -> dict[str, Any] | None:
    if context.active_context_ref is None:
        return None
    baseline = context.baselines.get(context.active_context_ref)
    if baseline is None:
        return None
    return {
        "context_ref": baseline.context_ref,
        "revision_ref": baseline.revision_ref,
        "network": _compact_mapping(baseline.network),
    }


def _active_model(context: AnalysisContext) -> dict[str, Any] | None:
    model = context.domain_state.model
    if model is None:
        return None
    return {
        "context_ref": model.context_ref,
        "revision_ref": model.revision_ref,
        "model_id": model.model_id,
        "source": model.source,
        "counts": _compact_mapping(model.counts),
    }


def _capability_status(context: AnalysisContext) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in sorted(context.domain_state.capabilities.values(), key=lambda value: value.id)
    ]


def _constraints(context: AnalysisContext) -> list[dict[str, Any]]:
    model = context.domain_state.model
    if model is None:
        return []
    applicable = [
        item
        for item in context.domain_state.constraints.values()
        if item.context_ref == model.context_ref and item.revision_ref == model.revision_ref
    ]
    return [
        {
            "constraint_ref": item.constraint_ref,
            "quantity": item.quantity,
            "subject_kind": item.subject_kind,
            "lower": item.lower,
            "upper": item.upper,
            "unit": item.unit,
            "applies_to_count": item.applies_to_count,
            "source_kind": item.source_kind,
            "source_ref": item.source_ref,
            "source": _compact_mapping(item.source),
        }
        for item in sorted(applicable, key=lambda value: value.constraint_ref)[:MAX_DOMAIN_RECORDS]
    ]


def _reusable_calculations(context: AnalysisContext) -> list[dict[str, Any]]:
    model = context.domain_state.model
    if model is None:
        return []
    applicable = [
        item
        for item in context.domain_state.calculations.values()
        if item.context_ref == model.context_ref and item.revision_ref == model.revision_ref
    ]
    return [
        {
            "result_ref": item.result_ref,
            "kind": item.kind,
            "status": item.status,
            "scenario_refs": sorted(item.scenario_refs),
            "solver": _compact_mapping(item.solver),
            "summary": _compact_mapping(item.summary),
            "artifact_path": item.artifact_path,
            "evidence_refs": sorted(item.evidence_refs),
            "producer_capability": item.producer_capability,
            "producer_turn_id": item.producer_turn_id,
        }
        for item in sorted(applicable, key=lambda value: value.result_ref)[:MAX_DOMAIN_RECORDS]
    ]


def _scenarios(context: AnalysisContext) -> list[dict[str, Any]]:
    model = context.domain_state.model
    if model is None:
        return []
    applicable = [
        item
        for item in context.domain_state.scenarios.values()
        if item.context_ref == model.context_ref and item.revision_ref == model.revision_ref
    ]
    return [
        {
            "scenario_ref": item.scenario_ref,
            "kind": item.kind,
            "status": item.status,
            "changes": _compact_mapping(item.changes),
            "result_refs": sorted(item.result_refs),
            "producer_turn_id": item.producer_turn_id,
        }
        for item in sorted(applicable, key=lambda value: value.scenario_ref)[:MAX_DOMAIN_RECORDS]
    ]


def _current_turn(context: AnalysisContext) -> dict[str, Any] | None:
    if context.current_turn is None:
        return None
    turn = context.current_turn
    return {
        "turn_id": turn.turn_id,
        "ordinal": turn.ordinal,
        "instruction_sha256": turn.instruction_sha256,
        "consumed_refs": sorted(turn.consumed_refs),
        "produced_refs": sorted(turn.produced_refs),
    }


def _completed_turns(context: AnalysisContext) -> list[dict[str, Any]]:
    return [
        {
            "turn_id": turn.turn_id,
            "ordinal": turn.ordinal,
            "status": turn.status,
            "answer_path": turn.answer_path,
            "consumed_refs": sorted(turn.consumed_refs),
            "produced_refs": sorted(turn.produced_refs),
        }
        for turn in sorted(context.turns, key=lambda item: (item.ordinal, item.turn_id))
    ]


def _reusable_results(context: AnalysisContext) -> list[dict[str, Any]]:
    model = context.domain_state.model
    return [
        {
            "result_ref": result.result_ref,
            "turn_id": result.turn_id,
            "capability": result.capability,
            "revision_ref": result.revision_ref,
            "path": result.path,
            "evidence_refs": sorted(result.evidence_refs),
            "solver_summary": _compact_mapping(result.solver_summary),
        }
        for result in sorted(context.results.values(), key=lambda item: item.result_ref)
        if model is None or result.revision_ref == model.revision_ref
    ]


def _verified_facts(context: AnalysisContext) -> dict[str, list[dict[str, Any]]]:
    facts_by_predicate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in sorted(context.verified_facts.values(), key=lambda item: item.fact_ref):
        item = _compact_fact(fact)
        facts_by_predicate[item["predicate"]].append(item)
    return {
        predicate: facts[:MAX_FACTS_PER_PREDICATE]
        for predicate, facts in sorted(facts_by_predicate.items())
    }


def _compact_fact(fact: VerifiedFact) -> dict[str, Any]:
    statement = _statement_payload(fact)
    predicate = str(statement.pop("predicate", "fact"))
    # These fields duplicate the native trajectory and the top-level evidence
    # lineage.  Keeping them in every promoted fact made the prompt view grow
    # quadratically with repeated observations.
    for key in (
        "evidence_refs",
        "producer_observation",
        "source_observation_id",
    ):
        statement.pop(key, None)
    compact = {
        "fact_ref": fact.fact_ref,
        "predicate": predicate,
        "statement": _compact_mapping(statement),
        "evidence_refs": sorted(fact.evidence_refs),
        "verifier_capability": fact.verifier_capability,
    }
    for promoted_key in ("subject", "branch_ref", "value", "unit", "context_ref", "revision_ref"):
        if promoted_key in compact["statement"]:
            compact[promoted_key] = compact["statement"].pop(promoted_key)
    if not compact["statement"]:
        compact.pop("statement")
    return compact


def _statement_payload(fact: VerifiedFact) -> dict[str, Any]:
    try:
        loaded = json.loads(fact.statement)
    except json.JSONDecodeError:
        return {"text": fact.statement}
    if isinstance(loaded, dict):
        return dict(loaded)
    return {"value": loaded}


def _unresolved_limitations(context: AnalysisContext) -> list[dict[str, Any]]:
    return [
        {
            "limitation_ref": limitation.limitation_ref,
            "turn_id": limitation.turn_id,
            "message": _compact_text(limitation.message),
            "refs": sorted(limitation.refs),
        }
        for limitation in sorted(context.unresolved_limitations, key=lambda item: item.limitation_ref)
    ]


def _compact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _compact_mapping(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _LARGE_FIELD_NAMES
        }
    if isinstance(value, list):
        if len(value) > 20:
            return {"omitted_count": len(value)}
        return [_compact_mapping(item) for item in value]
    if isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
        return {
            "text_prefix": value[:MAX_TEXT_CHARS],
            "omitted_characters": len(value) - MAX_TEXT_CHARS,
        }
    return value


def _compact_text(value: str) -> str:
    if len(value) <= MAX_TEXT_CHARS:
        return value
    omitted = len(value) - MAX_TEXT_CHARS
    return f"{value[:MAX_TEXT_CHARS]}… [{omitted} characters omitted]"


def _fit_within_budget(view: dict[str, Any]) -> dict[str, Any]:
    """Deterministically shed historical detail without blocking execution."""
    if _view_size(view) <= MAX_VIEW_BYTES:
        return view

    omissions: dict[str, int] = {}
    view["omitted_records"] = omissions

    facts = view["verified_facts"]
    while _view_size(view) > MAX_VIEW_BYTES and any(facts.values()):
        for predicate in sorted(facts):
            records = facts[predicate]
            if records:
                records.pop()
                key = f"verified_facts.{predicate}"
                omissions[key] = omissions.get(key, 0) + 1
            if _view_size(view) <= MAX_VIEW_BYTES:
                break

    # Reusable calculation summaries already carry the stable result/evidence
    # lineage, so detailed result records and historical scenarios are the next
    # safe material to shed.  Keep the most recently appended records.
    for key in (
        "reusable_results",
        "scenarios",
        "completed_turns",
        "reusable_calculations",
        "unresolved_limitations",
    ):
        records = view[key]
        while _view_size(view) > MAX_VIEW_BYTES and len(records) > 1:
            records.pop(0)
            omissions[key] = omissions.get(key, 0) + 1

    if _view_size(view) <= MAX_VIEW_BYTES:
        return view

    # This is a model-facing convenience projection, never an authority.  In
    # the pathological case retain only the live identity and operational
    # constraints; the complete history remains in the native trajectory.
    minimal = {
        key: view[key]
        for key in (
            "schema_version",
            "analysis_id",
            "revision",
            "state_hash",
            "status",
            "active_baseline",
            "active_model",
            "capability_status",
            "constraints",
            "current_turn",
            "unresolved_limitations",
        )
    }
    minimal["reusable_calculations"] = view["reusable_calculations"][-1:]
    minimal["scenarios"] = []
    minimal["completed_turns"] = view["completed_turns"][-1:]
    minimal["reusable_results"] = view["reusable_results"][-1:]
    minimal["verified_facts"] = {}
    minimal["omitted_records"] = {**omissions, "fallback_projection": 1}
    for key in ("unresolved_limitations", "capability_status", "constraints"):
        records = minimal[key]
        while _view_size(minimal) > MAX_VIEW_BYTES and records:
            records.pop(0)
            omission_key = f"fallback.{key}"
            minimal["omitted_records"][omission_key] = (
                minimal["omitted_records"].get(omission_key, 0) + 1
            )
    if _view_size(minimal) <= MAX_VIEW_BYTES:
        return minimal

    # Absolute last resort: preserve bounded live identity only.  All omitted
    # detail remains available in the native trajectory and report artifacts.
    active_model = minimal.get("active_model")
    bounded_model = None
    if isinstance(active_model, dict):
        bounded_model = {
            key: _bounded_identity(active_model.get(key))
            for key in ("context_ref", "revision_ref", "model_id", "source")
            if active_model.get(key) is not None
        }
    current_turn = minimal.get("current_turn")
    bounded_turn = None
    if isinstance(current_turn, dict):
        bounded_turn = {
            "turn_id": _bounded_identity(current_turn.get("turn_id")),
            "ordinal": current_turn.get("ordinal"),
        }
    return {
        "schema_version": CONTEXT_VIEW_VERSION,
        "analysis_id": _bounded_identity(minimal.get("analysis_id")),
        "revision": minimal.get("revision"),
        "state_hash": _bounded_identity(minimal.get("state_hash")),
        "status": _bounded_identity(minimal.get("status")),
        "active_model": bounded_model,
        "current_turn": bounded_turn,
        "omitted_records": {**minimal["omitted_records"], "identity_only_projection": 1},
    }


def _bounded_identity(value: Any) -> Any:
    if isinstance(value, str):
        return value[:256]
    return value


def _view_size(view: dict[str, Any]) -> int:
    return len(_canonical_json(view).encode("utf-8"))


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
