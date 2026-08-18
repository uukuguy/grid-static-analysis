from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError


class UnknownAnalysisOperationError(ValueError):
    def __init__(self, operation: str, allowed: tuple[str, ...]) -> None:
        super().__init__(operation)
        self.operation = operation
        self.allowed = allowed


class AnalysisOptionsError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisOutcome:
    operation: str
    status: str
    effective_options: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AnalysisOperation:
    identifier: str
    title: str
    pandapower_operation: str
    options_schema: dict[str, Any]
    execute: Callable[[Any, Any, dict[str, Any]], AnalysisOutcome]


_AC_OPTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "algorithm": {"type": "string", "enum": ["nr", "iwamoto_nr", "bfsw"]},
        "calculate_voltage_angles": {"type": "boolean"},
        "init": {"type": "string", "enum": ["auto", "flat", "dc", "results"]},
        "max_iteration": {"type": "integer", "minimum": 1, "maximum": 100},
        "tolerance_mva": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        "trafo_model": {"type": "string", "enum": ["t", "pi"]},
        "trafo_loading": {"type": "string", "enum": ["current", "power"]},
        "enforce_q_lims": {"type": "boolean"},
        "check_connectivity": {"type": "boolean"},
    },
}


def _run_ac(engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
    effective = dict(engine.ac_options)
    effective.update(options)
    engine.run_ac(net, effective)
    return AnalysisOutcome(
        operation="powerflow.ac",
        status="succeeded",
        effective_options=effective,
        metadata={"converged": bool(net.converged)},
    )


_OPERATIONS = {
    "powerflow.ac": AnalysisOperation(
        identifier="powerflow.ac",
        title="AC power flow",
        pandapower_operation="runpp",
        options_schema=_AC_OPTIONS_SCHEMA,
        execute=_run_ac,
    )
}


class AnalysisRegistry:
    """Version-pinned registry of simulator-owned static analysis operations."""

    def list(self) -> tuple[AnalysisOperation, ...]:
        return tuple(_OPERATIONS[key] for key in sorted(_OPERATIONS))

    def require(self, operation: str) -> AnalysisOperation:
        found = _OPERATIONS.get(operation)
        if found is None:
            raise UnknownAnalysisOperationError(operation, tuple(sorted(_OPERATIONS)))
        return found

    def describe(self, operation: str) -> dict[str, Any]:
        found = self.require(operation)
        return {
            "operation": found.identifier,
            "title": found.title,
            "pandapower_operation": found.pandapower_operation,
            "options_schema": found.options_schema,
        }

    def execute(self, operation: str, engine: Any, net: Any, options: dict[str, Any]) -> AnalysisOutcome:
        found = self.require(operation)
        try:
            Draft202012Validator(found.options_schema).validate(options)
        except JsonSchemaValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path)
            location = f" at {path}" if path else ""
            raise AnalysisOptionsError(f"options do not match {operation}{location}: {exc.message}") from exc
        return found.execute(engine, net, options)
