from __future__ import annotations

from typing import Any

import pandas as pd

from grid_simulator.analysis_registry import AnalysisOutcome
from grid_simulator.constraints import extract_model_constraints
from grid_simulator.models import ContextStore, ModelRegistry
from grid_simulator.results import ResultStore
from grid_simulator.workspace import SimulatorWorkspace


class DerivedResultError(ValueError):
    pass


def evaluate_result_violations(
    workspace: SimulatorWorkspace, engine: Any, source_result_ref: str
) -> dict[str, Any]:
    store = ResultStore(workspace)
    source = store.load(source_result_ref)
    context_ref = str(source["context_ref"])
    context_store = ContextStore(workspace, ModelRegistry(engine))
    context = context_store.require(context_ref)
    net = context_store.load_network(context_ref)
    constraints = extract_model_constraints(net, context.revision_ref)
    rows: list[dict[str, Any]] = []
    evaluated: list[str] = []
    unavailable: list[str] = []

    bus = source["datasets"].get("result.res_bus")
    if isinstance(bus, dict) and "vm_pu" in _fields(bus):
        evaluated.append("bus.vm_pu")
        for row in bus["rows"]:
            bound = constraints.bus_voltage.get(int(row["index"]))
            value = row.get("vm_pu")
            if bound is None or value is None:
                continue
            if bound.lower is not None and float(value) < bound.lower:
                rows.append(_violation(row, "bus_voltage_low", float(value), bound.lower, bound.constraint_ref, "warning"))
            if bound.upper is not None and float(value) > bound.upper:
                rows.append(_violation(row, "bus_voltage_high", float(value), bound.upper, bound.constraint_ref, "warning"))
    else:
        unavailable.append("bus.vm_pu")

    branch_evaluated = False
    for kind in ("line", "trafo", "trafo3w"):
        dataset = source["datasets"].get(f"result.res_{kind}")
        if not isinstance(dataset, dict) or "loading_percent" not in _fields(dataset):
            continue
        branch_evaluated = True
        for row in dataset["rows"]:
            bound = constraints.branch_loading.get((kind, int(row["index"])))
            value = row.get("loading_percent")
            if bound is None or bound.upper is None or value is None or float(value) <= bound.upper:
                continue
            rows.append(
                _violation(
                    row,
                    "branch_loading_high",
                    float(value),
                    bound.upper,
                    bound.constraint_ref,
                    "critical",
                )
            )
    (evaluated if branch_evaluated else unavailable).append("branch.loading_percent")
    net["res_violation"] = pd.DataFrame(
        rows,
        columns=[
            "kind",
            "severity",
            "asset_ref",
            "value",
            "limit",
            "deviation",
            "relative_deviation",
            "unit",
            "constraint_ref",
        ],
    )
    summary = {
        "source_result_ref": source_result_ref,
        "violation_count": len(rows),
        "evaluated_quantities": evaluated,
        "unavailable_quantities": unavailable,
        "constraint_source": "model",
    }
    persisted = store.persist(
        context=context,
        engine=engine,
        net=net,
        outcome=AnalysisOutcome(
            operation="constraints.violations",
            status="succeeded" if not unavailable else "partial",
            effective_options={"source_result_ref": source_result_ref},
            metadata=summary,
        ),
        capability_id="analysis.result.violations.evaluate",
    )
    return {
        "result_ref": persisted.result_ref,
        "source_result_ref": source_result_ref,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "status": persisted.document["status"],
        "summary": summary,
        "evidence_refs": [persisted.evidence_ref],
    }


def rank_result_risk(
    workspace: SimulatorWorkspace,
    engine: Any,
    source_result_ref: str,
    severity_weights: dict[str, float],
    limit: int,
) -> dict[str, Any]:
    store = ResultStore(workspace)
    source = store.load(source_result_ref)
    violations = source["datasets"].get("result.res_violation")
    if not isinstance(violations, dict):
        raise DerivedResultError("source result has no result.res_violation dataset")
    weights = {"info": 1.0, "warning": 2.0, "critical": 3.0, **severity_weights}
    ranked = []
    for row in violations["rows"]:
        severity = str(row["severity"])
        score = float(row["relative_deviation"]) * float(weights[severity])
        ranked.append({**row, "risk_score": score})
    ranked.sort(key=lambda row: (-float(row["risk_score"]), str(row.get("asset_ref"))))
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank

    context_ref = str(source["context_ref"])
    context_store = ContextStore(workspace, ModelRegistry(engine))
    context = context_store.require(context_ref)
    net = context_store.load_network(context_ref)
    net["res_risk"] = pd.DataFrame(ranked)
    summary = {
        "source_result_ref": source_result_ref,
        "ranked_count": len(ranked),
        "severity_weights": weights,
    }
    persisted = store.persist(
        context=context,
        engine=engine,
        net=net,
        outcome=AnalysisOutcome(
            operation="risk.rank",
            status="succeeded",
            effective_options={"source_result_ref": source_result_ref, "severity_weights": weights},
            metadata=summary,
        ),
        capability_id="analysis.result.risk.rank",
    )
    return {
        "result_ref": persisted.result_ref,
        "source_result_ref": source_result_ref,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "status": "succeeded",
        "summary": summary,
        "rankings": ranked[:limit],
        "evidence_refs": [persisted.evidence_ref],
    }


def _fields(dataset: dict[str, Any]) -> set[str]:
    return {str(field["name"]) for field in dataset["fields"]}


def _violation(
    row: dict[str, Any],
    kind: str,
    value: float,
    limit: float,
    constraint_ref: str,
    severity: str,
) -> dict[str, Any]:
    deviation = abs(value - limit)
    return {
        "kind": kind,
        "severity": severity,
        "asset_ref": row.get("asset_ref"),
        "value": value,
        "limit": limit,
        "deviation": deviation,
        "relative_deviation": deviation / abs(limit) if limit else deviation,
        "unit": "p.u." if kind.startswith("bus_voltage") else "percent",
        "constraint_ref": constraint_ref,
    }
