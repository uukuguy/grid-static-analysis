from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.capabilities.schema import CapabilityContract
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.evidence import fingerprint, write_network
from grid_simulator.protocol import CapabilityError, GridCapabilityRequest, GridCapabilityResponse
from grid_simulator.workspace import SimulatorWorkspace


EXECUTABLE_CAPABILITIES = frozenset({"environment.describe", "model.list", "context.open"})


def dispatch(request: GridCapabilityRequest, workspace_path: Path) -> GridCapabilityResponse:
    registry = CapabilityRegistry.load_packaged()
    try:
        result = _dispatch(request, SimulatorWorkspace(workspace_path), registry)
        _validate_result(registry.require(request.capability), result)
    except _OperationFailure as exc:
        return GridCapabilityResponse(request_id=request.request_id, ok=False, error=exc.error)
    return GridCapabilityResponse(request_id=request.request_id, ok=True, result=result)


def _dispatch(
    request: GridCapabilityRequest, workspace: SimulatorWorkspace, registry: CapabilityRegistry
) -> dict[str, Any]:
    if request.capability not in EXECUTABLE_CAPABILITIES:
        raise _failure("unsupported_capability", f"Capability {request.capability!r} is not implemented")
    if request.capability == "environment.describe":
        return {
            "protocol": "grid-capability",
            "protocol_version": "1.0",
            "simulator": "grid-simulator",
            "pandapower_version": "3.4.0",
            "executable_capabilities": [
                {"id": contract.id, "tool_name": contract.tool_name, "title": contract.title, "risk": contract.risk}
                for contract in registry.list()
                if contract.id in EXECUTABLE_CAPABILITIES
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
    raise _failure("unsupported_capability", f"Capability {request.capability!r} is not implemented")


def _validate_result(contract: CapabilityContract, result: dict[str, Any]) -> None:
    try:
        Draft202012Validator(contract.output_schema).validate(result)
    except JsonSchemaValidationError as exc:
        raise _failure(
            "contract_output_invalid",
            f"Capability {contract.id!r} produced a result that does not match its output contract",
        ) from exc


class _OperationFailure(Exception):
    def __init__(self, error: CapabilityError) -> None:
        self.error = error


def _failure(code: str, message: str) -> _OperationFailure:
    return _OperationFailure(CapabilityError(code=code, phase="execute", message=message))
