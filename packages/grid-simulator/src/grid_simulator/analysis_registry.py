from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from grid_simulator.bindings import OPERATIONS
from grid_simulator.bindings.base import AnalysisOperation, AnalysisOutcome


class UnknownAnalysisOperationError(ValueError):
    def __init__(self, operation: str, allowed: tuple[str, ...]) -> None:
        super().__init__(operation)
        self.operation = operation
        self.allowed = allowed


class AnalysisOptionsError(ValueError):
    pass


_OPERATIONS = {operation.identifier: operation for operation in OPERATIONS}


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
