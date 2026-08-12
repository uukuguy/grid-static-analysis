from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue


@dataclass(frozen=True)
class ToolResultEvent:
    capability: str
    result: Mapping[str, JsonValue]
    evidence_refs: tuple[str, ...]


def contains_all(answer: str, arguments: Mapping[str, object]) -> bool:
    values = arguments.get("values", [])
    return (
        isinstance(values, Sequence)
        and not isinstance(values, (str, bytes, bytearray))
        and all(str(value).casefold() in answer.casefold() for value in values)
    )


def truthful_limitation(answer: str, arguments: Mapping[str, object]) -> bool:
    lowered = answer.casefold()
    return any(term in lowered for term in ("不存在", "未找到", "不支持", "limitation", "not found"))


def declared_fields_match(actual: JsonValue, expected: JsonValue) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and declared_fields_match(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def topology_branch_endpoints(event: ToolResultEvent, arguments: Mapping[str, JsonValue]) -> bool:
    return event.capability == "topology.branch.endpoints.get" and declared_fields_match(
        event.result, dict(arguments)
    )


ORACLES = {
    "contains_all": contains_all,
    "truthful_limitation": truthful_limitation,
    "topology_branch_endpoints": topology_branch_endpoints,
}
