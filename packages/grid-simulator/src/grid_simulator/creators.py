from __future__ import annotations

import hashlib
import inspect
import json
import re
from typing import Any

import pandapower.create as pp_create
from pandapower.protection.protection_devices.fuse import Fuse


class UnknownCreatorError(ValueError):
    def __init__(self, creator: str, allowed: tuple[str, ...]) -> None:
        super().__init__(creator)
        self.creator = creator
        self.allowed = allowed


class CreatorArgumentsError(ValueError):
    pass


class UnknownElementReferenceError(ValueError):
    pass


def _creator_bindings() -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for name in dir(pp_create):
        function = getattr(pp_create, name)
        if (
            name.startswith("create_")
            and inspect.isfunction(function)
            and function.__module__.startswith("pandapower.create")
        ):
            parameters = list(inspect.signature(function).parameters.values())
            if parameters and parameters[0].name == "net":
                bindings[name.removeprefix("create_")] = function
    bindings["protection_fuse"] = _create_protection_fuse
    return bindings


def _create_protection_fuse(
    net: Any,
    switch_index: int,
    fuse_type: str = "none",
    rated_i_a: float = 0,
    characteristic_index: int | None = None,
    in_service: bool = True,
    curve_select: int = 0,
    z_ohm: float = 0.0001,
    name: str | None = None,
) -> int:
    device = Fuse(
        net,
        switch_index=switch_index,
        fuse_type=fuse_type,
        rated_i_a=rated_i_a,
        characteristic_index=characteristic_index,
        in_service=in_service,
        curve_select=curve_select,
        z_ohm=z_ohm,
        name=name,
    )
    return int(device.index)


_CREATORS = _creator_bindings()
_LOCAL_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_REFERENCE_ARGUMENTS = frozenset(
    {
        "bus",
        "buses",
        "element",
        "elements",
        "from_bus",
        "to_bus",
        "hv_bus",
        "mv_bus",
        "lv_bus",
        "line",
        "lines",
        "trafo",
        "trafos",
        "switch",
        "switch_index",
        "switches",
    }
)


class CreatorRegistry:
    """Pinned, introspectable allowlist for pandapower 3.4.0 element creators."""

    @property
    def version(self) -> str:
        payload = [
            [creator, str(inspect.signature(function))]
            for creator, function in sorted(_CREATORS.items())
        ]
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"pandapower-3.4.0:sha256:{digest}"

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(_CREATORS))

    def summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "id": creator,
                "required_arguments": [
                    parameter["name"]
                    for parameter in self.describe(creator)["parameters"]
                    if parameter["required"]
                ],
            }
            for creator in self.list()
        ]

    def describe(self, creator: str) -> dict[str, Any]:
        function = self.require(creator)
        parameters = []
        for parameter in inspect.signature(function).parameters.values():
            if parameter.name == "net":
                continue
            required = (
                parameter.default is inspect.Parameter.empty
                and parameter.kind
                not in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}
            )
            item: dict[str, Any] = {
                "name": parameter.name,
                "required": required,
                "kind": parameter.kind.name.lower(),
                "annotation": _annotation_name(parameter.annotation),
                "accepts_element_ref": _accepts_element_ref(parameter.name),
            }
            if not required:
                item["default_repr"] = _default_repr(parameter.default)
            parameters.append(item)
        doc = inspect.getdoc(function) or ""
        return {
            "creator": creator,
            "function": f"{function.__module__}.{function.__name__}",
            "summary": doc.splitlines()[0].strip() if doc else "",
            "parameters": parameters,
        }

    def require(self, creator: str) -> Any:
        function = _CREATORS.get(creator)
        if function is None:
            raise UnknownCreatorError(creator, self.list())
        return function

    def apply_elements(self, net: Any, elements: list[dict[str, Any]]) -> dict[str, Any]:
        references: dict[str, Any] = {}
        for element in elements:
            self.apply_element(net, element, references)
        return references

    def apply_element(
        self, net: Any, element: dict[str, Any], references: dict[str, Any]
    ) -> Any:
        local_id = str(element["id"])
        if not _LOCAL_ID.fullmatch(local_id) or local_id in references:
            raise CreatorArgumentsError(f"invalid or duplicate local element id: {local_id}")
        creator = str(element["creator"])
        function = self.require(creator)
        arguments = self._resolve(dict(element.get("arguments", {})), references)
        self._validate(function, arguments)
        try:
            created = _json_index(function(net, **arguments))
        except Exception as exc:
            raise CreatorArgumentsError(f"creator {creator!r} failed: {exc}") from exc
        references[local_id] = created
        return created

    def _resolve(self, value: Any, references: dict[str, Any]) -> Any:
        if isinstance(value, dict) and set(value) == {"element_ref"}:
            key = str(value["element_ref"])
            if key not in references:
                raise UnknownElementReferenceError(key)
            return references[key]
        if isinstance(value, dict):
            return {key: self._resolve(item, references) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve(item, references) for item in value]
        return value

    def _validate(self, function: Any, arguments: dict[str, Any]) -> None:
        signature = inspect.signature(function)
        parameters = {
            name: parameter
            for name, parameter in signature.parameters.items()
            if name != "net"
        }
        unknown = sorted(set(arguments) - set(parameters))
        missing = sorted(
            name
            for name, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}
            and name not in arguments
        )
        if unknown or missing:
            raise CreatorArgumentsError(
                f"unknown arguments={unknown}; missing arguments={missing}"
            )


def _accepts_element_ref(name: str) -> bool:
    return (
        name in _REFERENCE_ARGUMENTS
        or name.endswith("_bus")
        or name.endswith("_buses")
        or name.endswith("_element")
        or name.endswith("_elements")
    )


def _annotation_name(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "unspecified"
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", repr(annotation))


def _default_repr(default: Any) -> str:
    if default is inspect.Parameter.empty:
        return "variadic"
    text = repr(default)
    return text if len(text) <= 200 else text[:197] + "..."


def _json_index(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return value
