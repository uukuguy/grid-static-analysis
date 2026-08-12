from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pandapower.auxiliary import LoadflowNotConverged

from grid_simulator.evidence import canonical_json, fingerprint, write_json
from grid_simulator.models import OpenedContext
from grid_simulator.queries import BranchRecord, asset_ref, find_branch, list_branch_records, list_bus_records
from grid_simulator.workspace import SimulatorWorkspace


POWERFLOW_CAPABILITY_ID = "analysis.powerflow.ac.run"
CONTINGENCY_CAPABILITY_ID = "analysis.contingency.n_minus_one.run"
AC_SOLVER_PROFILE = "ac-default-v1"
RECOVERY_ACTIONS_NON_CONVERGENCE = (
    "inspect_network_diagnostics",
    "change_solver_profile",
    "report_non_convergence",
)
BRANCH_RANK_METRIC_UNITS = {
    "loading_percent": "percent",
    "p_from_mw": "MW",
    "p_to_mw": "MW",
    "pl_mw": "MW",
}
_RESULT_REF_PATTERN = re.compile(r"^result:sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class PersistedDocument:
    ref: str
    path: Path
    document: dict[str, Any]


@dataclass(frozen=True)
class NonConvergenceEvidence:
    evidence_ref: str
    artifact_ref: str


def run_ac_powerflow(
    *,
    workspace: SimulatorWorkspace,
    engine: Any,
    context: OpenedContext,
    net: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    solver = _solver(arguments, engine)
    try:
        engine.run_ac(net, solver["options"])
    except LoadflowNotConverged:
        raise
    except Exception as exc:
        raise PowerflowExecutionError("pandapower AC power flow failed") from exc

    document = _powerflow_document(
        capability_id=POWERFLOW_CAPABILITY_ID,
        context=context,
        engine=engine,
        net=net,
        solver=solver,
    )
    persisted = _persist_result(workspace.results_dir, "powerflow", document)
    evidence_ref = _persist_evidence(
        workspace,
        {
            "evidence_type": "analysis_result",
            "capability_id": POWERFLOW_CAPABILITY_ID,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "result_ref": persisted.ref,
            "facts": {
                "converged": True,
                "total_active_loss": persisted.document["losses"]["total_active_loss"],
                "branch_result_count": len(persisted.document["branch_results"]),
            },
            "provenance": _provenance(engine),
        },
    )
    return {
        "result_ref": persisted.ref,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "converged": True,
        "solver": _solver_summary(solver),
        "total_active_loss": persisted.document["losses"]["total_active_loss"],
        "evidence_refs": [evidence_ref],
    }


def rank_branches(*, workspace: SimulatorWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    result_ref = str(arguments["result_ref"])
    document = _load_powerflow_result(workspace, result_ref)
    metric = str(arguments["metric"])
    direction = str(arguments.get("direction", "descending"))
    limit = int(arguments["limit"])
    element_kind = arguments.get("element_kind")
    rows = [
        row
        for row in document["branch_results"]
        if element_kind is None or row["element_kind"] == str(element_kind)
    ]
    ranked = sorted(rows, key=lambda row: _rank_key(row, metric, direction))[:limit]
    unit = BRANCH_RANK_METRIC_UNITS[metric]
    return {
        "result_ref": result_ref,
        "context_ref": document["context_ref"],
        "revision_ref": document["revision_ref"],
        "metric": metric,
        "metric_unit": unit,
        "direction": direction,
        "branches": [
            {
                "branch_ref": row["branch_ref"],
                "element_kind": row["element_kind"],
                "pandapower_index": row["pandapower_index"],
                "metric_value": row[metric],
                "unit": unit,
                "loading_percent": row["loading_percent"],
                "p_from_mw": row["p_from_mw"],
                "p_to_mw": row["p_to_mw"],
                "pl_mw": row["pl_mw"],
            }
            for row in ranked
        ],
    }


def run_n_minus_one(
    *,
    workspace: SimulatorWorkspace,
    engine: Any,
    context: OpenedContext,
    net: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    branch_refs = [str(item) for item in arguments["branch_refs"]]
    branches = [_resolve_branch(net, context.revision_ref, branch_ref) for branch_ref in branch_refs]
    solver = _solver(arguments, engine)
    violation_types = set(arguments.get("violation_types", _default_violation_types()))
    scenarios = []
    evidence_refs = []
    for scenario_index, branch in enumerate(branches):
        scenario_net = copy.deepcopy(net)
        _open_branch(scenario_net, branch)
        scenario = _run_contingency_scenario(
            workspace=workspace,
            engine=engine,
            context=context,
            net=scenario_net,
            solver=solver,
            branch=branch,
            scenario_index=scenario_index,
            violation_types=violation_types,
        )
        scenarios.append(scenario)
        evidence_refs.append(scenario["evidence_ref"])

    status = _aggregate_status([str(scenario["status"]) for scenario in scenarios])
    aggregate_document = {
        "result_type": "analysis.contingency.n_minus_one.aggregate",
        "capability_id": CONTINGENCY_CAPABILITY_ID,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "policy": str(arguments["policy"]),
        "status": status,
        "solver": _solver_summary(solver),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "evidence_refs": evidence_refs,
        "provenance": _provenance(engine),
    }
    persisted = _persist_result(workspace.results_dir, "contingency", aggregate_document)
    return {
        "result_ref": persisted.ref,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "policy": str(arguments["policy"]),
        "status": status,
        "solver": _solver_summary(solver),
        "evidence_refs": evidence_refs,
        "scenarios": scenarios,
    }


def persist_non_convergence_diagnostics(
    *,
    workspace: SimulatorWorkspace,
    engine: Any,
    context: OpenedContext,
    capability_id: str,
    subject_ref: str | None = None,
) -> NonConvergenceEvidence:
    document: dict[str, Any] = {
        "evidence_type": "powerflow_non_convergence",
        "capability_id": capability_id,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "subject_ref": subject_ref,
        "diagnostic": "pandapower.LoadflowNotConverged",
        "allowed_recovery_actions": list(RECOVERY_ACTIONS_NON_CONVERGENCE),
        "provenance": _provenance(engine),
    }
    evidence_ref = _persist_evidence(workspace, document)
    artifact_ref = _persist_artifact(workspace, "powerflow-diagnostics", document)
    return NonConvergenceEvidence(evidence_ref=evidence_ref, artifact_ref=artifact_ref)


def evidence_path(workspace: SimulatorWorkspace, evidence_ref: str) -> Path | None:
    match = re.fullmatch(r"^evidence:sha256:([0-9a-f]{64})$", evidence_ref)
    if match is None:
        return None
    digest = match.group(1)
    for directory, prefix in (
        (workspace.root / "evidence" / "network-facts", "network-fact"),
        (workspace.root / "evidence" / "analysis", "analysis-evidence"),
    ):
        path = directory / f"{prefix}-{digest}.json"
        if path.is_file():
            return path
    return None


class PowerflowExecutionError(Exception):
    pass


class UnknownResultError(Exception):
    pass


class ResultIntegrityError(Exception):
    pass


class UnknownBranchError(Exception):
    pass


def _run_contingency_scenario(
    *,
    workspace: SimulatorWorkspace,
    engine: Any,
    context: OpenedContext,
    net: Any,
    solver: dict[str, Any],
    branch: BranchRecord,
    scenario_index: int,
    violation_types: set[str],
) -> dict[str, Any]:
    try:
        engine.run_ac(net, solver["options"])
    except LoadflowNotConverged:
        diagnostic = persist_non_convergence_diagnostics(
            workspace=workspace,
            engine=engine,
            context=context,
            capability_id=CONTINGENCY_CAPABILITY_ID,
            subject_ref=branch.asset_ref,
        )
        scenario_document = {
            "result_type": "analysis.contingency.n_minus_one.scenario",
            "capability_id": CONTINGENCY_CAPABILITY_ID,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "scenario_index": scenario_index,
            "outage": branch.summary(),
            "status": "non_converged",
            "converged": False,
            "violations": _filter_violations([_non_convergence_violation(branch.asset_ref)], violation_types),
            "evidence_ref": diagnostic.evidence_ref,
            "provenance": _provenance(engine),
        }
        scenario_result = _persist_result(workspace.results_dir, "contingency-scenario", scenario_document)
        return {
            "scenario_result_ref": scenario_result.ref,
            "branch_ref": branch.asset_ref,
            "element_kind": branch.kind,
            "pandapower_index": branch.index,
            "status": "non_converged",
            "converged": False,
            "violations": _filter_violations([_non_convergence_violation(branch.asset_ref)], violation_types),
            "evidence_ref": diagnostic.evidence_ref,
        }
    except Exception as exc:
        raise PowerflowExecutionError("pandapower contingency power flow failed") from exc

    powerflow = _powerflow_document(
        capability_id=CONTINGENCY_CAPABILITY_ID,
        context=context,
        engine=engine,
        net=net,
        solver=solver,
        extra={"outage": branch.summary(), "scenario_index": scenario_index},
    )
    violations = _filter_violations(_violations(powerflow), violation_types)
    max_loading_percent = _max_line_loading(powerflow)
    scenario_status = "succeeded"
    scenario_document = {
        "result_type": "analysis.contingency.n_minus_one.scenario",
        "capability_id": CONTINGENCY_CAPABILITY_ID,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "scenario_index": scenario_index,
        "outage": branch.summary(),
        "status": scenario_status,
        "converged": True,
        "max_loading_percent": max_loading_percent,
        "violations": violations,
        "powerflow": powerflow,
        "provenance": _provenance(engine),
    }
    scenario_result = _persist_result(workspace.results_dir, "contingency-scenario", scenario_document)
    evidence_ref = _persist_evidence(
        workspace,
        {
            "evidence_type": "contingency_scenario",
            "capability_id": CONTINGENCY_CAPABILITY_ID,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "result_ref": scenario_result.ref,
            "subject_ref": branch.asset_ref,
            "facts": {
                "status": scenario_status,
                "max_loading_percent": max_loading_percent,
                "violation_count": len(violations),
            },
            "provenance": _provenance(engine),
        },
    )
    return {
        "scenario_result_ref": scenario_result.ref,
        "branch_ref": branch.asset_ref,
        "element_kind": branch.kind,
        "pandapower_index": branch.index,
        "status": scenario_status,
        "converged": True,
        "max_loading_percent": max_loading_percent,
        "violations": violations,
        "evidence_ref": evidence_ref,
    }


def _solver(arguments: dict[str, Any], engine: Any) -> dict[str, Any]:
    profile = str(arguments.get("solver_profile", AC_SOLVER_PROFILE))
    options = dict(engine.ac_options)
    for key in (
        "algorithm",
        "calculate_voltage_angles",
        "init",
        "max_iteration",
        "tolerance_mva",
        "trafo_model",
        "trafo_loading",
        "enforce_q_lims",
        "check_connectivity",
    ):
        if key in arguments:
            options[key] = arguments[key]
    return {"profile": profile, "operation": "pandapower.runpp", "options": options}


def _rank_key(row: dict[str, Any], metric: str, direction: str) -> tuple[bool, float]:
    value = row[metric]
    if value is None:
        return (True, 0.0)
    numeric = float(value)
    return (False, numeric if direction == "ascending" else -numeric)


def _default_violation_types() -> set[str]:
    return {"line_overload", "bus_voltage_low", "bus_voltage_high", "non_convergence"}


def _filter_violations(violations: list[dict[str, Any]], allowed: set[str]) -> list[dict[str, Any]]:
    return [violation for violation in violations if str(violation["kind"]) in allowed]


def _solver_summary(solver: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": solver["profile"],
        "operation": solver["operation"],
        "algorithm": solver["options"]["algorithm"],
        "calculate_voltage_angles": solver["options"]["calculate_voltage_angles"],
        "init": solver["options"]["init"],
        "max_iteration": solver["options"]["max_iteration"],
        "tolerance_mva": solver["options"]["tolerance_mva"],
        "trafo_model": solver["options"]["trafo_model"],
        "trafo_loading": solver["options"]["trafo_loading"],
        "enforce_q_lims": solver["options"]["enforce_q_lims"],
        "check_connectivity": solver["options"]["check_connectivity"],
    }


def _powerflow_document(
    *,
    capability_id: str,
    context: OpenedContext,
    engine: Any,
    net: Any,
    solver: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document = {
        "result_type": "analysis.powerflow.ac",
        "capability_id": capability_id,
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        "engine": engine.name,
        "pandapower_version": engine.version,
        "solver": _solver_summary(solver),
        "convergence": {"converged": bool(net.converged)},
        "losses": {"total_active_loss": {"value": _total_active_loss(net), "unit": "MW"}},
        "bus_results": _bus_results(net, context.revision_ref),
        "branch_results": _branch_results(net, context.revision_ref),
        "transformer_results": _transformer_results(net, context.revision_ref),
        "generator_results": _element_results(net, context.revision_ref, "gen", "res_gen"),
        "load_results": _element_results(net, context.revision_ref, "load", "res_load"),
        "external_grid_results": _element_results(net, context.revision_ref, "ext_grid", "res_ext_grid"),
        "provenance": _provenance(engine),
    }
    if extra:
        document.update(extra)
    return document


def _bus_results(net: Any, revision_ref: str) -> list[dict[str, Any]]:
    rows = []
    bus_records = {record.index: record for record in list_bus_records(net, revision_ref)}
    for index, row in net.res_bus.iterrows():
        record = bus_records[int(index)]
        rows.append(
            {
                "asset_ref": record.asset_ref,
                "pandapower_index": int(index),
                "name": record.name,
                "vm_pu": _json_value(row.get("vm_pu")),
                "va_degree": _json_value(row.get("va_degree")),
                "p_mw": _json_value(row.get("p_mw")),
                "q_mvar": _json_value(row.get("q_mvar")),
            }
        )
    return rows


def _branch_results(net: Any, revision_ref: str) -> list[dict[str, Any]]:
    records = {(record.kind, record.index): record for record in list_branch_records(net, revision_ref)}
    rows = []
    for index, row in net.res_line.iterrows():
        record = records[("line", int(index))]
        rows.append(_branch_result_row(record, row))
    for index, row in net.res_trafo.iterrows():
        record = records[("trafo", int(index))]
        rows.append(
            _branch_result_row(
                record,
                row,
                p_from_field="p_hv_mw",
                p_to_field="p_lv_mw",
                q_from_field="q_hv_mvar",
                q_to_field="q_lv_mvar",
            )
        )
    if hasattr(net, "res_trafo3w"):
        for index, row in net.res_trafo3w.iterrows():
            record = records[("trafo3w", int(index))]
            rows.append(_branch_result_row(record, row, p_from_field="p_hv_mw", p_to_field="p_mv_mw"))
    return rows


def _branch_result_row(
    record: BranchRecord,
    row: Any,
    *,
    p_from_field: str = "p_from_mw",
    p_to_field: str = "p_to_mw",
    q_from_field: str = "q_from_mvar",
    q_to_field: str = "q_to_mvar",
) -> dict[str, Any]:
    return {
        "asset_ref": record.asset_ref,
        "branch_ref": record.asset_ref,
        "element_kind": record.kind,
        "pandapower_index": record.index,
        "name": record.name,
        "alias": record.alias,
        "from_bus_ref": record.from_bus_ref,
        "to_bus_ref": record.to_bus_ref,
        "loading_percent": _json_value(row.get("loading_percent")),
        "p_from_mw": _json_value(row.get(p_from_field)),
        "p_to_mw": _json_value(row.get(p_to_field)),
        "q_from_mvar": _json_value(row.get(q_from_field)),
        "q_to_mvar": _json_value(row.get(q_to_field)),
        "pl_mw": _json_value(row.get("pl_mw")),
        "ql_mvar": _json_value(row.get("ql_mvar")),
    }


def _transformer_results(net: Any, revision_ref: str) -> list[dict[str, Any]]:
    records = {(record.kind, record.index): record for record in list_branch_records(net, revision_ref)}
    rows = []
    for index, row in net.res_trafo.iterrows():
        record = records[("trafo", int(index))]
        payload = _table_row(row)
        payload.update({"asset_ref": record.asset_ref, "pandapower_index": int(index)})
        rows.append(payload)
    return rows


def _element_results(net: Any, revision_ref: str, kind: str, result_table: str) -> list[dict[str, Any]]:
    table = getattr(net, result_table)
    rows = []
    for index, row in table.iterrows():
        payload = _table_row(row)
        payload.update({"asset_ref": asset_ref(revision_ref, kind, int(index)), "pandapower_index": int(index)})
        rows.append(payload)
    return rows


def _table_row(row: Any) -> dict[str, Any]:
    return {str(column): _json_value(row.get(column)) for column in row.index}


def _total_active_loss(net: Any) -> float:
    total = float(net.res_line["pl_mw"].sum())
    if hasattr(net, "res_trafo"):
        total += float(net.res_trafo["pl_mw"].sum())
    if hasattr(net, "res_trafo3w") and "pl_mw" in net.res_trafo3w:
        total += float(net.res_trafo3w["pl_mw"].sum())
    return total


def _violations(powerflow: dict[str, Any]) -> list[dict[str, Any]]:
    violations = []
    for row in powerflow["branch_results"]:
        if row["element_kind"] == "line" and row["loading_percent"] is not None and row["loading_percent"] > 100.0:
            violations.append(
                {
                    "kind": "line_overload",
                    "severity": "critical",
                    "asset_ref": row["branch_ref"],
                    "element_kind": row["element_kind"],
                    "pandapower_index": row["pandapower_index"],
                    "value": row["loading_percent"],
                    "limit": 100.0,
                    "unit": "percent",
                }
            )
    for row in powerflow["bus_results"]:
        if row["vm_pu"] is not None and row["vm_pu"] < 0.95:
            violations.append(
                {
                    "kind": "bus_voltage_low",
                    "severity": "warning",
                    "asset_ref": row["asset_ref"],
                    "pandapower_index": row["pandapower_index"],
                    "value": row["vm_pu"],
                    "limit": 0.95,
                    "unit": "p.u.",
                }
            )
        if row["vm_pu"] is not None and row["vm_pu"] > 1.05:
            violations.append(
                {
                    "kind": "bus_voltage_high",
                    "severity": "warning",
                    "asset_ref": row["asset_ref"],
                    "pandapower_index": row["pandapower_index"],
                    "value": row["vm_pu"],
                    "limit": 1.05,
                    "unit": "p.u.",
                }
            )
    return violations


def _max_line_loading(powerflow: dict[str, Any]) -> float:
    values = [
        row["loading_percent"]
        for row in powerflow["branch_results"]
        if row["element_kind"] == "line" and row["loading_percent"] is not None
    ]
    return float(max(values)) if values else 0.0


def _non_convergence_violation(branch_ref: str) -> dict[str, Any]:
    return {
        "kind": "non_convergence",
        "severity": "critical",
        "asset_ref": branch_ref,
        "unit": None,
    }


def _resolve_branch(net: Any, revision_ref: str, branch_ref: str) -> BranchRecord:
    match = re.fullmatch(r"asset:(line|trafo|trafo3w):sha256:[0-9a-f]{64}", branch_ref)
    if match is None:
        raise UnknownBranchError("branch reference is malformed")
    branch = find_branch(net, revision_ref, match.group(1), "asset_ref", branch_ref)
    if branch is None:
        raise UnknownBranchError("branch reference does not resolve against context revision")
    return branch


def _open_branch(net: Any, branch: BranchRecord) -> None:
    if branch.kind == "line":
        net.line.at[branch.index, "in_service"] = False
    elif branch.kind == "trafo":
        net.trafo.at[branch.index, "in_service"] = False
    elif branch.kind == "trafo3w":
        net.trafo3w.at[branch.index, "in_service"] = False
    else:
        raise UnknownBranchError("unsupported branch kind")


def _aggregate_status(statuses: list[str]) -> Literal["succeeded", "partial", "failed"]:
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    if any(status == "succeeded" for status in statuses):
        return "partial"
    return "failed"


def _load_powerflow_result(workspace: SimulatorWorkspace, result_ref: str) -> dict[str, Any]:
    match = _RESULT_REF_PATTERN.fullmatch(result_ref)
    if match is None:
        raise UnknownResultError("result reference is malformed")
    path = workspace.result_document("powerflow", match.group(1))
    if not path.is_file():
        raise UnknownResultError("powerflow result is unavailable in this workspace")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ResultIntegrityError("powerflow result document is not UTF-8 JSON") from exc
    except OSError as exc:
        raise ResultIntegrityError("powerflow result document could not be read") from exc
    except json.JSONDecodeError as exc:
        raise ResultIntegrityError("powerflow result document is not valid JSON") from exc
    _verify_powerflow_result_document(document, result_ref)
    return document


def _verify_powerflow_result_document(document: object, result_ref: str) -> None:
    if not isinstance(document, dict):
        raise ResultIntegrityError("powerflow result document is malformed")
    if document.get("result_ref") != result_ref:
        raise ResultIntegrityError("powerflow result document reference does not match requested reference")
    body = {key: value for key, value in document.items() if key != "result_ref"}
    try:
        digest = fingerprint(canonical_json(body))
    except (TypeError, ValueError) as exc:
        raise ResultIntegrityError("powerflow result document is not canonical JSON") from exc
    if result_ref != f"result:sha256:{digest}":
        raise ResultIntegrityError("powerflow result document content does not match result reference")
    if document.get("result_type") != "analysis.powerflow.ac":
        raise ResultIntegrityError("powerflow result document has an unsupported result type")
    if not isinstance(document.get("context_ref"), str) or not isinstance(document.get("revision_ref"), str):
        raise ResultIntegrityError("powerflow result document is missing context references")
    branch_results = document.get("branch_results")
    if not isinstance(branch_results, list):
        raise ResultIntegrityError("powerflow result document is missing branch results")
    required_branch_fields = {
        "branch_ref",
        "element_kind",
        "pandapower_index",
        "loading_percent",
        "p_from_mw",
        "p_to_mw",
        "pl_mw",
    }
    for row in branch_results:
        if not isinstance(row, dict) or not required_branch_fields <= row.keys():
            raise ResultIntegrityError("powerflow result document has malformed branch results")


def _persist_result(directory: Path, prefix: str, document: dict[str, Any]) -> PersistedDocument:
    digest = fingerprint(canonical_json(document))
    result_ref = f"result:sha256:{digest}"
    persisted = {"result_ref": result_ref, **document}
    path = directory / f"{prefix}-{digest}.json"
    write_json(path, persisted)
    return PersistedDocument(ref=result_ref, path=path, document=persisted)


def _persist_evidence(workspace: SimulatorWorkspace, document: dict[str, Any]) -> str:
    digest = fingerprint(canonical_json(document))
    evidence_ref = f"evidence:sha256:{digest}"
    write_json(workspace.root / "evidence" / "analysis" / f"analysis-evidence-{digest}.json", document)
    return evidence_ref


def _persist_artifact(workspace: SimulatorWorkspace, prefix: str, document: dict[str, Any]) -> str:
    digest = fingerprint(canonical_json(document))
    artifact_ref = f"artifact:sha256:{digest}"
    write_json(workspace.root / "evidence" / "artifacts" / f"{prefix}-{digest}.json", document)
    return artifact_ref


def _provenance(engine: Any) -> dict[str, Any]:
    return {"engine": engine.name, "engine_version": engine.version}


def _json_value(value: object) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value.item() if hasattr(value, "item") else value
