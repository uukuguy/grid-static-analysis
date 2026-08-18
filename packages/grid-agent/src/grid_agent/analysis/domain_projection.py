from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from grid_agent.analysis.capabilities import CapabilityContextSpec
from grid_agent.analysis.models import (
    ActiveModelState,
    CalculationState,
    ConstraintState,
    DomainStateDelta,
    ScenarioState,
)


def project_domain_result(
    spec: CapabilityContextSpec,
    *,
    result: Mapping[str, Any],
    arguments: Mapping[str, Any],
    turn_id: str,
    result_paths: Mapping[str, str],
    active_revision_ref: str | None,
) -> DomainStateDelta:
    if spec.projector == "model-context-v1":
        return _model_context(spec, result, turn_id, active_revision_ref)
    if spec.projector == "model-constraints-v1":
        return _model_constraints(spec, result, turn_id)
    if spec.projector == "powerflow-ac-v1":
        return _calculation(
            spec,
            result,
            turn_id,
            result_paths,
            status="converged" if result.get("converged") else "failed",
        )
    if spec.projector == "analysis-result-v1":
        return _generic_analysis(spec, result, turn_id, result_paths)
    if spec.projector == "contingency-n1-v1":
        return _contingency(spec, result, arguments, turn_id, result_paths)
    return DomainStateDelta(projector=spec.projector)


def _generic_analysis(
    spec: CapabilityContextSpec,
    result: Mapping[str, Any],
    turn_id: str,
    result_paths: Mapping[str, str],
) -> DomainStateDelta:
    projected = dict(result)
    projected["status"] = str(result.get("status", "unknown"))
    datasets = result.get("datasets")
    if isinstance(datasets, list):
        projected["dataset_count"] = len(datasets)
    return _calculation(
        spec,
        projected,
        turn_id,
        result_paths,
        status=str(result.get("status", "unknown")),
    )


def _model_context(
    spec: CapabilityContextSpec,
    result: Mapping[str, Any],
    turn_id: str,
    active_revision_ref: str | None,
) -> DomainStateDelta:
    context_ref = _required_string(result, "context_ref")
    revision_ref = result.get("revision_ref") or active_revision_ref
    if not isinstance(revision_ref, str):
        raise ValueError("model context projection requires revision_ref")
    model_id = result.get("model")
    if not isinstance(model_id, str):
        raise ValueError("model context projection requires model")
    source = result.get("source")
    if not isinstance(source, str):
        source = "registered"
    counts = result.get("counts")
    return DomainStateDelta(
        projector=spec.projector,
        model=ActiveModelState(
            context_ref=context_ref,
            revision_ref=revision_ref,
            model_id=model_id,
            source=source,
            counts={str(key): int(value) for key, value in counts.items() if isinstance(value, int)}
            if isinstance(counts, Mapping)
            else {},
        ),
    )


def _model_constraints(
    spec: CapabilityContextSpec,
    result: Mapping[str, Any],
    turn_id: str,
) -> DomainStateDelta:
    context_ref = _required_string(result, "context_ref")
    revision_ref = _required_string(result, "revision_ref")
    evidence_refs = _string_list(result.get("evidence_refs"))
    if not evidence_refs:
        raise ValueError("model constraint projection requires evidence")
    records = []
    for raw in _mapping_list(result.get("constraints")):
        source = raw.get("source")
        source_mapping = dict(source) if isinstance(source, Mapping) else {}
        records.append(
            ConstraintState(
                constraint_ref=_required_string(raw, "constraint_ref"),
                context_ref=context_ref,
                revision_ref=revision_ref,
                quantity=_required_string(raw, "quantity"),
                subject_kind=_required_string(raw, "subject_kind"),
                lower=_optional_float(raw.get("lower")),
                upper=_optional_float(raw.get("upper")),
                unit=_required_string(raw, "unit"),
                applies_to_count=int(raw["applies_to_count"]),
                source_kind="model",
                source_ref=evidence_refs[0],
                source=source_mapping,
                producer_capability=spec.capability,
                producer_turn_id=turn_id,
            )
        )
    return DomainStateDelta(projector=spec.projector, constraints=records)


def _calculation(
    spec: CapabilityContextSpec,
    result: Mapping[str, Any],
    turn_id: str,
    result_paths: Mapping[str, str],
    *,
    status: str,
    scenario_refs: list[str] | None = None,
) -> DomainStateDelta:
    result_ref = _required_string(result, "result_ref")
    summary = {}
    for field in (
        "total_active_loss",
        "constraint_evaluation",
        "status",
        "operation",
        "dataset_count",
        "summary",
    ):
        if field in result:
            summary[field] = result[field]
    calculation = CalculationState(
        result_ref=result_ref,
        kind=spec.result_kind or spec.capability,
        context_ref=_required_string(result, "context_ref"),
        revision_ref=_required_string(result, "revision_ref"),
        scenario_refs=scenario_refs or [],
        status=status,
        solver=dict(result["solver"]) if isinstance(result.get("solver"), Mapping) else {},
        summary=summary,
        artifact_path=result_paths.get(result_ref, ""),
        evidence_refs=_string_list(result.get("evidence_refs")),
        producer_capability=spec.capability,
        producer_turn_id=turn_id,
    )
    if not calculation.artifact_path:
        raise ValueError(f"calculation projection requires artifact path: {result_ref}")
    return DomainStateDelta(projector=spec.projector, calculations=[calculation])


def _contingency(
    spec: CapabilityContextSpec,
    result: Mapping[str, Any],
    arguments: Mapping[str, Any],
    turn_id: str,
    result_paths: Mapping[str, str],
) -> DomainStateDelta:
    context_ref = _required_string(result, "context_ref")
    revision_ref = _required_string(result, "revision_ref")
    scenarios = []
    requested_branches = _string_list(arguments.get("branch_refs"))
    for index, raw in enumerate(_mapping_list(result.get("scenarios"))):
        scenario_ref = _required_string(raw, "scenario_result_ref")
        branch_ref = raw.get("branch_ref")
        if not isinstance(branch_ref, str) and index < len(requested_branches):
            branch_ref = requested_branches[index]
        changes = {"outage_branch_ref": branch_ref} if isinstance(branch_ref, str) else {}
        scenarios.append(
            ScenarioState(
                scenario_ref=scenario_ref,
                context_ref=context_ref,
                revision_ref=revision_ref,
                kind="single_branch_outage",
                status=_required_string(raw, "status"),
                changes=changes,
                result_refs=[scenario_ref],
                producer_capability=spec.capability,
                producer_turn_id=turn_id,
            )
        )
    projected = _calculation(
        spec,
        result,
        turn_id,
        result_paths,
        status=str(result.get("status", "unknown")),
        scenario_refs=[item.scenario_ref for item in scenarios],
    )
    return projected.model_copy(update={"scenarios": scenarios})


def _required_string(mapping: Mapping[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"domain projection requires {field}")
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
