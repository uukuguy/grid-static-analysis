from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JsonSchemaSchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.capabilities.schema import CapabilityContract
from grid_simulator.engine import Pandapower340Engine
from grid_simulator.models import (
    ContextIntegrityError,
    ContextNotFoundError,
    ContextStore,
    InvalidContextRef,
    ModelNotFoundError,
    ModelRegistry,
)
from grid_simulator.protocol import CapabilityError, GridCapabilityRequest, GridCapabilityResponse
from grid_simulator.workspace import SimulatorWorkspace


EXECUTABLE_CAPABILITIES = frozenset({"environment.describe", "model.list", "context.open", "context.get"})


def dispatch(request: GridCapabilityRequest, workspace_path: Path) -> GridCapabilityResponse:
    registry = CapabilityRegistry.load_packaged()
    try:
        if request.capability not in EXECUTABLE_CAPABILITIES:
            raise _unsupported_capability(request.capability)
        contract = _require_contract(registry, request.capability)
        _validate_arguments(contract, request.arguments)
        result = _dispatch(request, SimulatorWorkspace(workspace_path), registry)
        _validate_result(contract, result)
    except _OperationFailure as exc:
        return GridCapabilityResponse(request_id=request.request_id, ok=False, error=exc.error)
    return GridCapabilityResponse(request_id=request.request_id, ok=True, result=result)


def _dispatch(
    request: GridCapabilityRequest, workspace: SimulatorWorkspace, registry: CapabilityRegistry
) -> dict[str, Any]:
    if request.capability not in EXECUTABLE_CAPABILITIES:
        raise _unsupported_capability(request.capability)
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
        return {
            "models": [
                {"model": model.model_id, "source": model.source, "pandapower_version": model.engine_version}
                for model in ModelRegistry(Pandapower340Engine()).list()
            ]
        }
    if request.capability == "context.open":
        engine = Pandapower340Engine()
        registry = ModelRegistry(engine)
        store = ContextStore(workspace, registry)
        try:
            context = store.create(str(request.arguments["model"]))
        except ModelNotFoundError as exc:
            raise _failure(
                "model_not_found",
                f"Model {exc.model_id!r} is not registered",
                phase="resolve",
                allowed_recovery_actions=("call_model_list",),
            ) from exc
        model = registry.list()[0]
        net = store.load_network(context.context_ref)
        return {
            "context_ref": context.context_ref,
            "model": context.model_id,
            "engine": engine.name,
            "pandapower_version": engine.version,
            "source": model.source,
            "semantic_sha256": context.revision_ref.removeprefix("revision:sha256:"),
            "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
        }
    if request.capability == "context.get":
        engine = Pandapower340Engine()
        store = ContextStore(workspace, ModelRegistry(engine))
        try:
            context = store.require(str(request.arguments["context_ref"]))
            net = store.load_network(context.context_ref)
        except (InvalidContextRef, ContextNotFoundError, ContextIntegrityError) as exc:
            raise _failure(
                "unknown_context",
                "Context reference is not available or failed verification",
                phase="resolve",
                allowed_recovery_actions=("call_context_open",),
            ) from exc
        return {
            "context_ref": context.context_ref,
            "model": context.model_id,
            "counts": {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))},
        }
    raise _unsupported_capability(request.capability)


def _require_contract(registry: CapabilityRegistry, capability: str) -> CapabilityContract:
    try:
        return registry.require(capability)
    except KeyError as exc:
        raise _failure(
            "capability_contract_unavailable",
            f"Capability {capability!r} contract is unavailable",
            phase="resolve",
        ) from exc


def _validate_arguments(contract: CapabilityContract, arguments: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(contract.input_schema)
        Draft202012Validator(contract.input_schema).validate(arguments)
    except JsonSchemaSchemaError as exc:
        raise _failure(
            "capability_input_schema_invalid",
            f"Capability {contract.id!r} has an invalid input contract",
            phase="resolve",
        ) from exc
    except JsonSchemaValidationError as exc:
        raise _failure(
            "invalid_arguments",
            "Capability arguments do not match the input contract",
            phase="validate",
            allowed_recovery_actions=("correct_arguments",),
        ) from exc


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


def _unsupported_capability(capability: str) -> _OperationFailure:
    return _failure("unsupported_capability", f"Capability {capability!r} is not implemented")


def _failure(
    code: str,
    message: str,
    *,
    phase: Literal["parse", "resolve", "validate", "execute", "persist"] = "execute",
    allowed_recovery_actions: tuple[str, ...] = (),
) -> _OperationFailure:
    return _OperationFailure(
        CapabilityError(
            code=code,
            phase=phase,
            message=message,
            allowed_recovery_actions=allowed_recovery_actions,
        )
    )
