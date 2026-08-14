from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from grid_simulator.evidence import canonical_json, fingerprint


@dataclass(frozen=True)
class ElementConstraint:
    constraint_ref: str
    lower: float | None
    upper: float | None


@dataclass(frozen=True)
class ModelConstraints:
    summaries: tuple[dict[str, Any], ...]
    bus_voltage: dict[int, ElementConstraint]
    branch_loading: dict[tuple[str, int], ElementConstraint]

    def evaluation_summary(self) -> dict[str, Any]:
        evaluated = []
        unevaluated = []
        if self.bus_voltage:
            evaluated.append("bus.vm_pu")
        else:
            unevaluated.append("bus.vm_pu")
        if self.branch_loading:
            evaluated.append("branch.loading_percent")
        else:
            unevaluated.append("branch.loading_percent")
        status = "evaluated" if not unevaluated else "partially_evaluated" if evaluated else "not_defined"
        return {
            "status": status,
            "source": "model",
            "evaluated_quantities": evaluated,
            "unevaluated_quantities": unevaluated,
        }


def extract_model_constraints(net: Any, revision_ref: str) -> ModelConstraints:
    summaries: list[dict[str, Any]] = []
    bus_voltage: dict[int, ElementConstraint] = {}
    branch_loading: dict[tuple[str, int], ElementConstraint] = {}

    bus_groups = _groups(net.bus, lower_field="min_vm_pu", upper_field="max_vm_pu")
    for (lower, upper), indices in bus_groups.items():
        summary = _summary(
            revision_ref=revision_ref,
            quantity="bus.vm_pu",
            subject_kind="bus",
            lower=lower,
            upper=upper,
            unit="p.u.",
            indices=indices,
            table="bus",
            fields=("min_vm_pu", "max_vm_pu"),
        )
        summaries.append(summary)
        bound = ElementConstraint(summary["constraint_ref"], lower, upper)
        bus_voltage.update({index: bound for index in indices})

    for kind, table in (("line", net.line), ("trafo", net.trafo)):
        groups = _groups(table, lower_field=None, upper_field="max_loading_percent")
        for (lower, upper), indices in groups.items():
            summary = _summary(
                revision_ref=revision_ref,
                quantity="branch.loading_percent",
                subject_kind=kind,
                lower=lower,
                upper=upper,
                unit="percent",
                indices=indices,
                table=kind,
                fields=("max_loading_percent",),
            )
            summaries.append(summary)
            bound = ElementConstraint(summary["constraint_ref"], lower, upper)
            branch_loading.update({(kind, index): bound for index in indices})

    return ModelConstraints(
        summaries=tuple(sorted(summaries, key=lambda item: str(item["constraint_ref"]))),
        bus_voltage=bus_voltage,
        branch_loading=branch_loading,
    )


def describe_model_constraints(net: Any, revision_ref: str) -> dict[str, Any]:
    constraints = extract_model_constraints(net, revision_ref)
    return {"constraints": [dict(item) for item in constraints.summaries]}


def evaluate_constraints(
    powerflow: Mapping[str, Any], constraints: ModelConstraints
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for row in powerflow["branch_results"]:
        key = (str(row["element_kind"]), int(row["pandapower_index"]))
        bound = constraints.branch_loading.get(key)
        value = row.get("loading_percent")
        if bound is not None and bound.upper is not None and value is not None and float(value) > bound.upper:
            violations.append(
                {
                    "kind": "line_overload",
                    "severity": "critical",
                    "asset_ref": row["branch_ref"],
                    "element_kind": row["element_kind"],
                    "pandapower_index": row["pandapower_index"],
                    "value": value,
                    "limit": bound.upper,
                    "unit": "percent",
                    "constraint_ref": bound.constraint_ref,
                    "constraint_source": "model",
                }
            )
    for row in powerflow["bus_results"]:
        bound = constraints.bus_voltage.get(int(row["pandapower_index"]))
        value = row.get("vm_pu")
        if bound is None or value is None:
            continue
        if bound.lower is not None and float(value) < bound.lower:
            violations.append(_voltage_violation(row, value, bound, kind="bus_voltage_low", limit=bound.lower))
        if bound.upper is not None and float(value) > bound.upper:
            violations.append(_voltage_violation(row, value, bound, kind="bus_voltage_high", limit=bound.upper))
    return violations, constraints.evaluation_summary()


def _groups(
    table: Any,
    *,
    lower_field: str | None,
    upper_field: str | None,
) -> dict[tuple[float | None, float | None], list[int]]:
    groups: dict[tuple[float | None, float | None], list[int]] = {}
    for raw_index, row in table.iterrows():
        lower = _number(row.get(lower_field)) if lower_field is not None else None
        upper = _number(row.get(upper_field)) if upper_field is not None else None
        if lower is None and upper is None:
            continue
        groups.setdefault((lower, upper), []).append(int(raw_index))
    return groups


def _summary(
    *,
    revision_ref: str,
    quantity: str,
    subject_kind: str,
    lower: float | None,
    upper: float | None,
    unit: str,
    indices: list[int],
    table: str,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    identity = {
        "revision_ref": revision_ref,
        "quantity": quantity,
        "subject_kind": subject_kind,
        "lower": lower,
        "upper": upper,
        "indices": sorted(indices),
        "table": table,
        "fields": list(fields),
    }
    return {
        "constraint_ref": f"constraint:sha256:{fingerprint(canonical_json(identity))}",
        "quantity": quantity,
        "subject_kind": subject_kind,
        "lower": lower,
        "upper": upper,
        "unit": unit,
        "applies_to_count": len(indices),
        "source": {"kind": "model", "table": table, "fields": list(fields)},
    }


def _voltage_violation(
    row: Mapping[str, Any],
    value: Any,
    bound: ElementConstraint,
    *,
    kind: str,
    limit: float,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": "warning",
        "asset_ref": row["asset_ref"],
        "pandapower_index": row["pandapower_index"],
        "value": value,
        "limit": limit,
        "unit": "p.u.",
        "constraint_ref": bound.constraint_ref,
        "constraint_source": "model",
    }


def _number(value: Any) -> float | None:
    if value is None or bool(pd.isna(value)):
        return None
    return float(value)
