from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]+$")
_TOOL_NAME_PATTERN = re.compile(r"^grid_[a-z0-9_]+$")
_JSON_SCHEMA_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


class ToolCatalogError(ValueError):
    """Raised when semantic capability documents cannot be materialized."""


@dataclass(frozen=True, slots=True)
class ToolDocument:
    name: str
    capability: str
    description: str
    input_schema: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capability": self.capability,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolCatalog:
    def __init__(self, tools: tuple[ToolDocument, ...]) -> None:
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names):
            raise ToolCatalogError("tool names must be unique")
        capabilities = [tool.capability for tool in tools]
        if len(set(capabilities)) != len(capabilities):
            raise ToolCatalogError("capabilities must be unique")
        self.tools = tuple(sorted(tools, key=lambda tool: tool.name))
        self._by_name = {tool.name: tool for tool in self.tools}

    @classmethod
    def from_documents(cls, documents: tuple[dict[str, object], ...] | list[dict[str, object]]) -> "ToolCatalog":
        return cls(tuple(_materialize_tool(document) for document in documents))

    @classmethod
    def from_environment(
        cls,
        documents: tuple[dict[str, object], ...] | list[dict[str, object]],
        environment_description: dict[str, object],
    ) -> "ToolCatalog":
        executable = environment_description.get("executable_capabilities")
        if not isinstance(executable, list):
            raise ToolCatalogError("environment.describe result must include executable_capabilities")
        executable_ids = []
        for item in executable:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ToolCatalogError("environment.describe executable_capabilities must contain ids")
            executable_ids.append(item["id"])

        by_id = {str(document.get("id")): document for document in documents}
        missing = [capability_id for capability_id in executable_ids if capability_id not in by_id]
        if missing:
            raise ToolCatalogError(f"missing capability documents: {', '.join(missing)}")
        selected = [by_id[capability_id] for capability_id in executable_ids]
        environment_by_id = {
            str(item["id"]): item for item in executable if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for document in selected:
            capability_id = str(document["id"])
            if document.get("availability") != "published":
                raise ToolCatalogError(f"executable capability {capability_id} is not published")
            announced = environment_by_id[capability_id]
            for field in ("availability", "context_effect"):
                if field in announced and announced[field] != document.get(field):
                    raise ToolCatalogError(f"environment {field} does not match capability document: {capability_id}")
        return cls.from_documents(selected)

    def require(self, name: str) -> ToolDocument:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def materialize(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "protocol": "grid-tool-catalog",
            "version": "1.0",
            "tools": [tool.as_json() for tool in self.tools],
        }
        fingerprint = "sha256:" + hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
        payload = {"fingerprint": fingerprint, **body}
        path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
        return path


def load_packaged_capability_documents(repository_root: Path) -> tuple[dict[str, object], ...]:
    definitions = (
        Path(repository_root)
        / "packages/grid-simulator/src/grid_simulator/capabilities/definitions"
    )
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(definitions.glob("*.json"), key=lambda item: item.name)
    )


def _materialize_tool(document: dict[str, object]) -> ToolDocument:
    _validate_document(document)
    input_schema = document["input_schema"]
    assert isinstance(input_schema, dict)
    return ToolDocument(
        name=str(document["tool_name"]),
        capability=str(document["id"]),
        description=_description(document),
        input_schema=input_schema,
    )


def _validate_document(document: dict[str, object]) -> None:
    required = (
        "id",
        "tool_name",
        "availability",
        "context_effect",
        "purpose",
        "applies_to",
        "not_for",
        "input_schema",
        "requires",
        "produces",
        "common_next",
        "recovery",
    )
    for field in required:
        if field not in document:
            raise ToolCatalogError(f"capability document missing {field}")
    if not isinstance(document["id"], str) or not _CAPABILITY_ID_PATTERN.fullmatch(document["id"]):
        raise ToolCatalogError("capability id is invalid")
    if not isinstance(document["tool_name"], str) or not _TOOL_NAME_PATTERN.fullmatch(document["tool_name"]):
        raise ToolCatalogError("tool_name is invalid")
    if document["availability"] != "published":
        raise ToolCatalogError(f"capability {document['id']} is not published")
    context_effect = document["context_effect"]
    if not isinstance(context_effect, dict):
        raise ToolCatalogError("context_effect must be an object")
    required_context_fields = {
        "requires_state",
        "consumes_state",
        "produces_state",
        "invalidates_state",
        "result_kind",
        "projector",
    }
    if set(context_effect) != required_context_fields:
        raise ToolCatalogError("context_effect fields are invalid")
    for field in ("requires_state", "consumes_state", "produces_state", "invalidates_state"):
        if not isinstance(context_effect[field], list) or not all(isinstance(item, str) for item in context_effect[field]):
            raise ToolCatalogError(f"context_effect.{field} must be a list of strings")
    if context_effect["result_kind"] is not None and not isinstance(context_effect["result_kind"], str):
        raise ToolCatalogError("context_effect.result_kind must be a string or null")
    if not isinstance(context_effect["projector"], str) or not context_effect["projector"]:
        raise ToolCatalogError("context_effect.projector is required")
    if not isinstance(document["purpose"], str) or not document["purpose"].strip():
        raise ToolCatalogError("purpose is required")
    for field in ("applies_to", "not_for", "requires", "produces", "common_next"):
        if not isinstance(document[field], list) or not all(isinstance(item, str) for item in document[field]):
            raise ToolCatalogError(f"{field} must be a list of strings")
    if not isinstance(document["recovery"], dict) or not all(
        isinstance(error, str)
        and isinstance(actions, list)
        and all(isinstance(action, str) for action in actions)
        for error, actions in document["recovery"].items()
    ):
        raise ToolCatalogError("recovery must map error strings to action lists")
    input_schema = document["input_schema"]
    if not isinstance(input_schema, dict):
        raise ToolCatalogError("input_schema must be a JSON object")
    _validate_json_schema(input_schema, path="input_schema")


def _validate_json_schema(schema: dict[str, Any], *, path: str) -> None:
    schema_type = schema.get("type")
    if schema_type is not None:
        if isinstance(schema_type, str):
            if schema_type not in _JSON_SCHEMA_TYPES:
                raise ToolCatalogError(f"{path} has invalid type")
        elif isinstance(schema_type, list):
            if not all(isinstance(item, str) and item in _JSON_SCHEMA_TYPES for item in schema_type):
                raise ToolCatalogError(f"{path} has invalid type")
        else:
            raise ToolCatalogError(f"{path} has invalid type")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ToolCatalogError(f"{path}.properties must be an object")
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, dict):
                raise ToolCatalogError(f"{path}.properties must contain schemas")
            _validate_json_schema(child, path=f"{path}.properties.{name}")
    for keyword in ("items", "not"):
        child = schema.get(keyword)
        if child is not None:
            if not isinstance(child, dict):
                raise ToolCatalogError(f"{path}.{keyword} must be a schema")
            _validate_json_schema(child, path=f"{path}.{keyword}")
    for keyword in ("oneOf", "anyOf", "allOf"):
        children = schema.get(keyword)
        if children is not None:
            if not isinstance(children, list) or not all(isinstance(child, dict) for child in children):
                raise ToolCatalogError(f"{path}.{keyword} must be a list of schemas")
            for index, child in enumerate(children):
                _validate_json_schema(child, path=f"{path}.{keyword}.{index}")


def _description(document: dict[str, object]) -> str:
    not_for = list(_strings(document["not_for"]))
    pandapower = document.get("pandapower")
    if isinstance(pandapower, dict):
        not_for.extend(_strings(pandapower.get("limitations", [])))
    if any("flow direction" in item or "power-flow direction" in item for item in not_for):
        not_for.append("不表示实时功率方向")
    applies_to = list(_strings(document["applies_to"]))
    terms = document.get("terms")
    if isinstance(terms, dict):
        applies_to.extend(_strings(terms.get("zh", [])))
        applies_to.extend(_strings(terms.get("en", [])))
    return "\n".join(
        (
            f"Purpose: {document['purpose']}",
            f"Use for: {_list_text(applies_to)}",
            f"Do not use for: {_list_text(not_for)}",
            f"Requires: {_list_text(_strings(document['requires']))}",
            f"Produces: {_list_text(_strings(document['produces']))}",
            f"Common next capabilities: {_list_text(_strings(document['common_next']))}",
            f"Recovery: {_recovery_text(document['recovery'])}",
        )
    )


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _list_text(values: list[str] | tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _recovery_text(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    parts = []
    for error in sorted(value):
        actions = value[error]
        parts.append(f"{error} -> {_list_text(_strings(actions))}")
    return "; ".join(parts)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
