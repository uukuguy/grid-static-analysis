from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class AnalysisPrerequisiteError(ValueError):
    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details = details


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


def closed_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def number(*, minimum: float | None = None, exclusive_minimum: float | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "number"}
    if minimum is not None:
        schema["minimum"] = minimum
    if exclusive_minimum is not None:
        schema["exclusiveMinimum"] = exclusive_minimum
    return schema


def integer(*, minimum: int = 1, maximum: int = 10000) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def bool_or_auto() -> dict[str, Any]:
    return {"anyOf": [{"type": "boolean"}, {"const": "auto"}]}


def int_or_auto(*, maximum: int = 10000) -> dict[str, Any]:
    return {"anyOf": [integer(maximum=maximum), {"const": "auto"}]}


def recycle_schema() -> dict[str, Any]:
    return nullable(
        closed_schema(
            {
                "trafo": {"type": "boolean"},
                "bus_pq": {"type": "boolean"},
                "gen": {"type": "boolean"},
            }
        )
    )


def effective(defaults: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    return {**defaults, **options}
