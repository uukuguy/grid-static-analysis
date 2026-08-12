from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.evidence import fingerprint, write_json, write_network
from grid_simulator.protocol import CapabilityError, GridCapabilityRequest, GridCapabilityResponse
from grid_simulator.workspace import SimulatorWorkspace


def dispatch(request: GridCapabilityRequest, workspace_path: Path) -> GridCapabilityResponse:
    try:
        result = _dispatch(request, SimulatorWorkspace(workspace_path))
    except _OperationFailure as exc:
        return GridCapabilityResponse(request_id=request.request_id, ok=False, error=exc.error)
    return GridCapabilityResponse(request_id=request.request_id, ok=True, result=result)


def _dispatch(request: GridCapabilityRequest, workspace: SimulatorWorkspace) -> dict[str, Any]:
    registry = CapabilityRegistry.load_packaged()
    if request.capability == "environment.describe":
        return {
            "protocol": "grid-capability",
            "protocol_version": "1.0",
            "simulator": "grid-simulator",
            "pandapower_version": "3.4.0",
            "capabilities": [
                {"id": contract.id, "tool_name": contract.tool_name, "title": contract.title, "risk": contract.risk}
                for contract in registry.list()
            ],
        }
    if request.capability == "model.list":
        return {"models": [{"model": "ieee39", "source": "pandapower.networks.case39", "pandapower_version": "3.4.0"}]}
    if request.capability == "context.open":
        if request.arguments.get("model") != "ieee39":
            raise _failure("unsupported_model", "Only the ieee39 model is supported")
        engine = Pandapower340Engine()
        net = engine.open_ieee39()
        serialized = engine.serialize(net)
        network_hash = fingerprint(serialized)
        write_network(workspace.networks_dir / f"{network_hash}.json", serialized)
        return {
            "context_ref": f"context:sha256:{network_hash}",
            "model": "ieee39",
            "engine": engine.name,
            "pandapower_version": engine.version,
            "source": "pandapower.networks.case39",
            "semantic_sha256": network_hash,
            "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
        }
    if request.capability in {"context.get", "model.element.get"}:
        net, network_hash = _opened_network(request.arguments)
        if request.capability == "context.get":
            return {
                "context_ref": f"context:sha256:{network_hash}",
                "model": "ieee39",
                "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
            }
        return _resolve_element(net, request.arguments)
    if request.capability == "analysis.powerflow.ac.run":
        net, network_hash = _opened_network(request.arguments)
        return _run_ac(net, network_hash, workspace)
    if request.capability == "result.branches.rank":
        return _rank_lines(request.arguments, workspace)
    if request.capability == "analysis.contingency.n_minus_one.run":
        net, network_hash = _opened_network(request.arguments)
        return _run_contingencies(net, network_hash, request.arguments, workspace)
    raise _failure("unsupported_capability", f"Capability {request.capability!r} is not implemented")


def _opened_network(arguments: dict[str, Any]):
    reference = arguments.get("context_ref")
    engine = Pandapower340Engine()
    net = engine.open_ieee39()
    network_hash = fingerprint(engine.serialize(net))
    expected = f"context:sha256:{network_hash}"
    if reference != expected:
        raise _failure("unknown_context", "Context reference is unknown or expired")
    return net, network_hash


def _resolve_element(net, arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("element") != "line" or arguments.get("namespace") != "pandapower_index":
        raise _failure("unsupported_element", "Only line elements addressed by pandapower index are supported")
    try:
        index = int(str(arguments.get("query")))
    except ValueError as exc:
        raise _failure("invalid_element_query", "Element query must be an integer index") from exc
    if index not in net.line.index:
        raise _failure("unknown_element", "Line index is not present in the network")
    row = net.line.loc[index]
    from_index, to_index = int(row.from_bus), int(row.to_bus)
    return {
        "element_id": f"line:index:{index}",
        "index": index,
        "from_bus": {"index": from_index, "name": str(net.bus.at[from_index, "name"])},
        "to_bus": {"index": to_index, "name": str(net.bus.at[to_index, "name"])},
    }


def _run_ac(net, network_hash: str, workspace: SimulatorWorkspace) -> dict[str, Any]:
    engine = Pandapower340Engine()
    try:
        engine.run_ac(net)
    except Exception as exc:
        raise _failure("powerflow_failed", "AC power flow did not converge") from exc
    if not bool(net.converged):
        raise _failure("powerflow_failed", "AC power flow did not converge")
    line_rows = _line_rows(net)
    total_loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum() + net.res_trafo3w.pl_mw.sum())
    document = {
        "network_fingerprint": network_hash,
        "engine": engine.name,
        "version": engine.version,
        "solver_options": engine.ac_options,
        "converged": True,
        "total_active_loss_mw": total_loss,
        "units": {"total_active_loss_mw": "MW", "loading_percent": "%"},
        "lines": line_rows,
    }
    result_hash = fingerprint(json.dumps(document, sort_keys=True, separators=(",", ":")))
    result_ref = f"result:sha256:{result_hash}"
    write_json(workspace.results_dir / f"{result_hash}.json", document)
    return {**document, "context_ref": f"context:sha256:{network_hash}", "result_ref": result_ref}


def _rank_lines(arguments: dict[str, Any], workspace: SimulatorWorkspace) -> dict[str, Any]:
    reference = arguments.get("result_ref")
    if not isinstance(reference, str) or not reference.startswith("result:sha256:"):
        raise _failure("invalid_result_ref", "A result_ref is required")
    result_path = workspace.results_dir / f"{reference.removeprefix('result:sha256:')}.json"
    if not result_path.is_file():
        raise _failure("unknown_result_ref", "Result reference is unknown or expired")
    document = json.loads(result_path.read_text(encoding="utf-8"))
    sort_key = arguments.get("metric", "loading_percent")
    if sort_key not in {"loading_percent", "p_from_mw", "p_to_mw", "pl_mw"}:
        raise _failure("invalid_metric", "Unsupported branch ranking metric")
    limit = arguments.get("limit", 5)
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise _failure("invalid_limit", "Line result limit must be an integer from 1 to 100")
    lines = sorted(document["lines"], key=lambda row: (-float(row[sort_key]), int(row["index"])))[:limit]
    return {"result_ref": reference, "metric": sort_key, "direction": "descending", "branches": lines}


def _run_contingencies(net, network_hash: str, arguments: dict[str, Any], workspace: SimulatorWorkspace) -> dict[str, Any]:
    if arguments.get("policy") != "static-analysis-v1":
        raise _failure("unsupported_policy", "Only static-analysis-v1 is supported")
    line_ids = arguments.get("line_ids")
    if not isinstance(line_ids, list) or not line_ids or len(line_ids) > 32 or len(set(line_ids)) != len(line_ids):
        raise _failure("invalid_line_ids", "Provide 1 to 32 unique stable line IDs")
    scenarios = []
    for line_id in line_ids:
        index = _line_index(line_id)
        if index not in net.line.index:
            raise _failure("unknown_element", "Line index is not present in the network")
        scenario_net = deepcopy(net)
        scenario_net.line.at[index, "in_service"] = False
        engine = Pandapower340Engine()
        try:
            engine.run_ac(scenario_net)
            converged = bool(scenario_net.converged)
        except Exception:
            converged = False
        if not converged:
            receipt = {"line_id": line_id, "converged": False, "evidence_id": None, "overloaded_lines": []}
        else:
            rows = _line_rows(scenario_net)
            overloaded = [row for row in rows if row["loading_percent"] > 100.0]
            receipt = {
                "line_id": line_id,
                "converged": True,
                "max_line_loading_percent": max(row["loading_percent"] for row in rows),
                "overloaded_lines": overloaded,
            }
            evidence_hash = fingerprint(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
            receipt["evidence_id"] = f"evidence:sha256:{evidence_hash}"
            write_json(workspace.results_dir / f"{evidence_hash}.json", {"network_fingerprint": network_hash, **receipt})
        scenarios.append(receipt)
    return {"context_ref": f"context:sha256:{network_hash}", "policy": "static-analysis-v1", "scenarios": scenarios}


def _line_index(line_id: object) -> int:
    if not isinstance(line_id, str) or not line_id.startswith("line:index:"):
        raise _failure("invalid_line_id", "Line IDs must use line:index:<integer>")
    try:
        return int(line_id.rsplit(":", 1)[1])
    except ValueError as exc:
        raise _failure("invalid_line_id", "Line IDs must use line:index:<integer>") from exc


def _line_rows(net) -> list[dict[str, Any]]:
    result = []
    for index, row in net.res_line.iterrows():
        result.append(
            {
                "element_id": f"line:index:{int(index)}",
                "index": int(index),
                "loading_percent": float(row.loading_percent),
                "p_from_mw": float(row.p_from_mw),
                "p_to_mw": float(row.p_to_mw),
                "pl_mw": float(row.pl_mw),
            }
        )
    return result


class _OperationFailure(Exception):
    def __init__(self, error: CapabilityError) -> None:
        self.error = error


def _failure(code: str, message: str) -> _OperationFailure:
    return _OperationFailure(CapabilityError(code=code, phase="execute", message=message))
