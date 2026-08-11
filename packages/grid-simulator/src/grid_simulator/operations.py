from __future__ import annotations

from pathlib import Path
from typing import Any

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.evidence import fingerprint, write_network
from grid_simulator.protocol import OperationError, SimulatorRequest, SimulatorResponse
from grid_simulator.workspace import SimulatorWorkspace


def dispatch(request: SimulatorRequest, workspace_path: Path) -> SimulatorResponse:
    try:
        result = _dispatch(request, SimulatorWorkspace(workspace_path))
    except _OperationFailure as exc:
        return SimulatorResponse(request_id=request.request_id, ok=False, error=exc.error)
    return SimulatorResponse(request_id=request.request_id, ok=True, result=result)


def _dispatch(request: SimulatorRequest, workspace: SimulatorWorkspace) -> dict[str, Any]:
    registry = CapabilityRegistry()
    if request.operation == "capabilities.list":
        return {"capabilities": registry.list()}
    if request.operation == "capabilities.describe":
        identifier = request.arguments.get("id")
        item = registry.describe(str(identifier)) if identifier is not None else None
        if item is None:
            raise _failure("unknown_capability", "Capability is not available")
        return {"capability": item}
    if request.operation == "network.open":
        if request.arguments.get("network") != "ieee39":
            raise _failure("unsupported_network", "Only the ieee39 network is supported")
        engine = Pandapower340Engine()
        net = engine.open_ieee39()
        serialized = engine.serialize(net)
        network_hash = fingerprint(serialized)
        write_network(workspace.networks_dir / f"{network_hash}.json", serialized)
        return {
            "network_ref": f"network:ieee39:{network_hash}",
            "engine": engine.name,
            "version": engine.version,
            "source": "pandapower.networks.case39",
            "semantic_sha256": network_hash,
            "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
        }
    if request.operation in {"network.describe", "element.resolve"}:
        net, network_hash = _opened_network(request.arguments)
        if request.operation == "network.describe":
            return {"network_ref": f"network:ieee39:{network_hash}", "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line))}}
        return _resolve_element(net, request.arguments)
    raise _failure("unsupported_operation", f"Operation {request.operation!r} is not implemented")


def _opened_network(arguments: dict[str, Any]):
    reference = arguments.get("network_ref")
    engine = Pandapower340Engine()
    net = engine.open_ieee39()
    network_hash = fingerprint(engine.serialize(net))
    expected = f"network:ieee39:{network_hash}"
    if reference != expected:
        raise _failure("unknown_network_ref", "Network reference is unknown or expired")
    return net, network_hash


def _resolve_element(net, arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("element") != "line" or arguments.get("namespace") != "index":
        raise _failure("unsupported_element", "Only line elements addressed by index are supported")
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


class _OperationFailure(Exception):
    def __init__(self, error: OperationError) -> None:
        self.error = error


def _failure(code: str, message: str) -> _OperationFailure:
    return _OperationFailure(OperationError(code=code, message=message))
