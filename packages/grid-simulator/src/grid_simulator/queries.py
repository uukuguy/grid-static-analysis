from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

import pandas as pd


ElementKind = Literal["bus", "line", "trafo", "trafo3w"]
DatasetName = Literal["network.buses", "network.branches"]


@dataclass(frozen=True)
class FieldMetadata:
    name: str
    type: str
    unit: str | None
    meaning: str
    provenance: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "type": self.type,
            "unit": self.unit,
            "meaning": self.meaning,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class BusRecord:
    asset_ref: str
    kind: Literal["bus"]
    index: int
    name: str
    alias: str
    vn_kv: float
    in_service: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_ref": self.asset_ref,
            "kind": self.kind,
            "index": self.index,
            "name": self.name,
            "alias": self.alias,
            "vn_kv": self.vn_kv,
            "in_service": self.in_service,
        }


@dataclass(frozen=True)
class BranchRecord:
    asset_ref: str
    kind: Literal["line", "trafo", "trafo3w"]
    index: int
    name: str
    alias: str
    from_bus_ref: str
    to_bus_ref: str
    from_bus_index: int
    to_bus_index: int
    from_bus_name: str
    to_bus_name: str
    in_service: bool
    length_km: float | None
    max_i_ka: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_ref": self.asset_ref,
            "kind": self.kind,
            "index": self.index,
            "name": self.name,
            "alias": self.alias,
            "from_bus_ref": self.from_bus_ref,
            "to_bus_ref": self.to_bus_ref,
            "from_bus_index": self.from_bus_index,
            "to_bus_index": self.to_bus_index,
            "from_bus_name": self.from_bus_name,
            "to_bus_name": self.to_bus_name,
            "in_service": self.in_service,
            "length_km": self.length_km,
            "max_i_ka": self.max_i_ka,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "asset_ref": self.asset_ref,
            "kind": self.kind,
            "index": self.index,
            "name": self.name,
            "alias": self.alias,
        }


BUS_FIELDS: tuple[FieldMetadata, ...] = (
    FieldMetadata("asset_ref", "asset_ref", None, "Stable content-addressed bus asset reference", "revision_ref,bus,index"),
    FieldMetadata("kind", "enum", None, "Element kind; always bus for this dataset", "domain_normalization"),
    FieldMetadata("index", "integer", None, "pandapower bus table index", "net.bus.index"),
    FieldMetadata("name", "string", None, "pandapower bus name label", "net.bus.name"),
    FieldMetadata("alias", "string", None, "Readable pandapower element alias", "pandapower_index"),
    FieldMetadata("vn_kv", "number", "kV", "Nominal bus voltage", "net.bus.vn_kv"),
    FieldMetadata("in_service", "boolean", None, "Whether the bus is in service", "net.bus.in_service"),
)

BRANCH_FIELDS: tuple[FieldMetadata, ...] = (
    FieldMetadata("asset_ref", "asset_ref", None, "Stable content-addressed branch asset reference", "revision_ref,kind,index"),
    FieldMetadata("kind", "enum", None, "Branch table kind", "domain_normalization"),
    FieldMetadata("index", "integer", None, "pandapower element table index", "net.<kind>.index"),
    FieldMetadata("name", "string", None, "pandapower element name or index label", "net.<kind>.name"),
    FieldMetadata("alias", "string", None, "Readable pandapower element alias", "pandapower_index"),
    FieldMetadata("from_bus_ref", "asset_ref", None, "First stored terminal bus reference; not flow direction", "branch endpoint table"),
    FieldMetadata("to_bus_ref", "asset_ref", None, "Second stored terminal bus reference; not flow direction", "branch endpoint table"),
    FieldMetadata("from_bus_index", "integer", None, "First stored terminal pandapower bus index", "branch endpoint table"),
    FieldMetadata("to_bus_index", "integer", None, "Second stored terminal pandapower bus index", "branch endpoint table"),
    FieldMetadata("from_bus_name", "string", None, "First stored terminal bus name", "net.bus.name"),
    FieldMetadata("to_bus_name", "string", None, "Second stored terminal bus name", "net.bus.name"),
    FieldMetadata("in_service", "boolean", None, "Whether the branch element is in service", "net.<kind>.in_service"),
    FieldMetadata("length_km", "number|null", "km", "Line length when available", "net.line.length_km"),
    FieldMetadata("max_i_ka", "number|null", "kA", "Line maximum current when available", "net.line.max_i_ka"),
)

DATASET_FIELDS: dict[str, tuple[FieldMetadata, ...]] = {
    "network.buses": BUS_FIELDS,
    "network.branches": BRANCH_FIELDS,
}

WHERE_FIELDS = frozenset({"kind", "in_service", "name", "alias", "asset_ref"})


def asset_ref(revision_ref: str, kind: str, index: int) -> str:
    payload = json.dumps([revision_ref, kind, index], separators=(",", ":"), ensure_ascii=False)
    return f"asset:{kind}:sha256:{sha256(payload.encode()).hexdigest()}"


def dataset_ref(revision_ref: str, dataset: str) -> str:
    payload = json.dumps([revision_ref, dataset], separators=(",", ":"), ensure_ascii=False)
    return f"dataset:{dataset}:sha256:{sha256(payload.encode()).hexdigest()}"


def records_for_dataset(net: Any, revision_ref: str, dataset: str) -> list[BusRecord | BranchRecord]:
    if dataset == "network.buses":
        return list_bus_records(net, revision_ref)
    if dataset == "network.branches":
        return list_branch_records(net, revision_ref)
    raise ValueError(f"unsupported dataset: {dataset}")


def list_bus_records(net: Any, revision_ref: str) -> list[BusRecord]:
    return [_bus_record(net, revision_ref, int(index)) for index in net.bus.index]


def list_branch_records(net: Any, revision_ref: str) -> list[BranchRecord]:
    records: list[BranchRecord] = []
    records.extend(_line_record(net, revision_ref, int(index)) for index in net.line.index)
    records.extend(_trafo_record(net, revision_ref, int(index)) for index in net.trafo.index)
    if hasattr(net, "trafo3w") and len(net.trafo3w.index) > 0:
        records.extend(_trafo3w_record(net, revision_ref, int(index)) for index in net.trafo3w.index)
    return records


def find_bus(net: Any, revision_ref: str, namespace: str, identifier: str) -> BusRecord | None:
    for record in list_bus_records(net, revision_ref):
        if _matches(record.as_dict(), namespace, identifier):
            return record
    return None


def find_branch(net: Any, revision_ref: str, kind: str, namespace: str, identifier: str) -> BranchRecord | None:
    if kind not in {"line", "trafo", "trafo3w"}:
        return None
    for record in list_branch_records(net, revision_ref):
        if record.kind == kind and _matches(record.as_dict(), namespace, identifier):
            return record
    return None


def select_fields(dataset: str, rows: list[dict[str, Any]], selected: list[str]) -> list[dict[str, Any]]:
    allowed = allowed_field_names(dataset)
    missing = [field for field in selected if field not in allowed]
    if missing:
        raise ValueError(f"unavailable fields: {missing}")
    return [{field: row[field] for field in selected} for row in rows]


def allowed_field_names(dataset: str) -> tuple[str, ...]:
    return tuple(field.name for field in DATASET_FIELDS[dataset])


def field_metadata(dataset: str) -> list[dict[str, str | None]]:
    return [field.as_dict() for field in DATASET_FIELDS[dataset]]


def _bus_record(net: Any, revision_ref: str, index: int) -> BusRecord:
    row = net.bus.loc[index]
    name = _name(row.get("name"), index)
    return BusRecord(
        asset_ref=asset_ref(revision_ref, "bus", index),
        kind="bus",
        index=index,
        name=name,
        alias=f"pandapower:bus:{index}",
        vn_kv=float(row["vn_kv"]),
        in_service=_bool_value(row.get("in_service", True)),
    )


def _line_record(net: Any, revision_ref: str, index: int) -> BranchRecord:
    row = net.line.loc[index]
    from_bus = int(row["from_bus"])
    to_bus = int(row["to_bus"])
    return _branch_record(
        net,
        revision_ref,
        kind="line",
        index=index,
        name=_name(row.get("name"), index),
        from_bus=from_bus,
        to_bus=to_bus,
        in_service=_bool_value(row.get("in_service", True)),
        length_km=_optional_float(row.get("length_km")),
        max_i_ka=_optional_float(row.get("max_i_ka")),
    )


def _trafo_record(net: Any, revision_ref: str, index: int) -> BranchRecord:
    row = net.trafo.loc[index]
    return _branch_record(
        net,
        revision_ref,
        kind="trafo",
        index=index,
        name=_name(row.get("name"), index),
        from_bus=int(row["hv_bus"]),
        to_bus=int(row["lv_bus"]),
        in_service=_bool_value(row.get("in_service", True)),
        length_km=None,
        max_i_ka=None,
    )


def _trafo3w_record(net: Any, revision_ref: str, index: int) -> BranchRecord:
    row = net.trafo3w.loc[index]
    return _branch_record(
        net,
        revision_ref,
        kind="trafo3w",
        index=index,
        name=_name(row.get("name"), index),
        from_bus=int(row["hv_bus"]),
        to_bus=int(row["mv_bus"]),
        in_service=_bool_value(row.get("in_service", True)),
        length_km=None,
        max_i_ka=None,
    )


def _branch_record(
    net: Any,
    revision_ref: str,
    *,
    kind: Literal["line", "trafo", "trafo3w"],
    index: int,
    name: str,
    from_bus: int,
    to_bus: int,
    in_service: bool,
    length_km: float | None,
    max_i_ka: float | None,
) -> BranchRecord:
    from_bus_record = _bus_record(net, revision_ref, from_bus)
    to_bus_record = _bus_record(net, revision_ref, to_bus)
    return BranchRecord(
        asset_ref=asset_ref(revision_ref, kind, index),
        kind=kind,
        index=index,
        name=name,
        alias=f"pandapower:{kind}:{index}",
        from_bus_ref=from_bus_record.asset_ref,
        to_bus_ref=to_bus_record.asset_ref,
        from_bus_index=from_bus_record.index,
        to_bus_index=to_bus_record.index,
        from_bus_name=from_bus_record.name,
        to_bus_name=to_bus_record.name,
        in_service=in_service,
        length_km=length_km,
        max_i_ka=max_i_ka,
    )


def _matches(row: dict[str, Any], namespace: str, identifier: str) -> bool:
    if namespace == "pandapower_index":
        try:
            return int(identifier) == row["index"]
        except ValueError:
            return False
    if namespace == "name":
        return str(row["name"]) == identifier
    if namespace == "alias":
        return str(row["alias"]) == identifier
    if namespace == "asset_ref":
        return str(row["asset_ref"]) == identifier
    return False


def _name(value: object, fallback_index: int) -> str:
    if value is None or pd.isna(value):
        return str(fallback_index)
    return str(value)


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _bool_value(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    return bool(value)
