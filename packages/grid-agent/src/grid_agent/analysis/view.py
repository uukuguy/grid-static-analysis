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
    """Raised when the provenance-preserving model-facing view exceeds its budget."""


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
    _assert_within_budget(view)
    return view


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
            "producer_observation": _compact_mapping(result.producer_observation),
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
            "message": limitation.message,
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
    return value


def _assert_within_budget(view: dict[str, Any]) -> None:
    size = len(_canonical_json(view).encode("utf-8"))
    if size > MAX_VIEW_BYTES:
        raise ContextViewTooLarge(f"analysis context view is {size} bytes; maximum is {MAX_VIEW_BYTES}")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
