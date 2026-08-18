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
    nullable: bool = False

    def as_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "type": self.type,
            "unit": self.unit,
            "meaning": self.meaning,
            "provenance": self.provenance,
            "nullable": self.nullable,
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


@dataclass(frozen=True)
class DynamicRecord:
    values: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)

    @property
    def asset_ref(self) -> str:
        return str(self.values["asset_ref"])


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

EXCLUDED_NETWORK_TABLES = frozenset({"controller", "characteristic", "spline", "piecewise_linear"})


def asset_ref(revision_ref: str, kind: str, index: Any) -> str:
    payload = json.dumps([revision_ref, kind, index], separators=(",", ":"), ensure_ascii=False)
    return f"asset:{kind}:sha256:{sha256(payload.encode()).hexdigest()}"


def dataset_ref(revision_ref: str, dataset: str) -> str:
    payload = json.dumps([revision_ref, dataset], separators=(",", ":"), ensure_ascii=False)
    return f"dataset:{dataset}:sha256:{sha256(payload.encode()).hexdigest()}"


def dataset_names(net: Any) -> tuple[str, ...]:
    names = ["network.buses", "network.branches"]
    names.extend(
        f"network.{name}"
        for name, table in sorted(net.items(), key=lambda item: str(item[0]))
        if _is_static_table(name, table)
    )
    return tuple(dict.fromkeys(names))


def records_for_dataset(net: Any, revision_ref: str, dataset: str) -> list[BusRecord | BranchRecord | DynamicRecord]:
    if dataset == "network.buses":
        return list_bus_records(net, revision_ref)
    if dataset == "network.branches":
        return list_branch_records(net, revision_ref)
    table_name = _table_name(dataset)
    if table_name is not None and dataset in dataset_names(net):
        table = net[table_name]
        return [DynamicRecord(_table_row(table_name, revision_ref, index, row)) for index, row in table.iterrows()]
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


def find_element(
    net: Any, revision_ref: str, kind: str, namespace: str, identifier: str
) -> BusRecord | BranchRecord | DynamicRecord | None:
    if kind == "bus":
        return find_bus(net, revision_ref, namespace, identifier)
    if kind in {"line", "trafo", "trafo3w"}:
        return find_branch(net, revision_ref, kind, namespace, identifier)
    dataset = f"network.{kind}"
    if dataset not in dataset_names(net):
        return None
    for record in records_for_dataset(net, revision_ref, dataset):
        if _matches(record.as_dict(), namespace, identifier):
            return record
    return None


def select_fields(dataset: str, rows: list[dict[str, Any]], selected: list[str]) -> list[dict[str, Any]]:
    allowed = allowed_field_names(dataset)
    missing = [field for field in selected if field not in allowed]
    if missing:
        raise ValueError(f"unavailable fields: {missing}")
    return [{field: row[field] for field in selected} for row in rows]


def allowed_field_names(dataset: str, net: Any | None = None) -> tuple[str, ...]:
    if dataset in DATASET_FIELDS:
        return tuple(field.name for field in DATASET_FIELDS[dataset])
    table_name = _table_name(dataset)
    if table_name is None or net is None or dataset not in dataset_names(net):
        raise ValueError(f"unsupported dataset: {dataset}")
    return ("asset_ref", "kind", "index", "alias", *(str(column) for column in net[table_name].columns))


def field_metadata(dataset: str, net: Any | None = None) -> list[dict[str, Any]]:
    if dataset in DATASET_FIELDS:
        return [field.as_dict() for field in DATASET_FIELDS[dataset]]
    table_name = _table_name(dataset)
    if table_name is None or net is None or dataset not in dataset_names(net):
        raise ValueError(f"unsupported dataset: {dataset}")
    table = net[table_name]
    fields = [
        FieldMetadata("asset_ref", "asset_ref", None, "Stable content-addressed element reference", f"{dataset}.index"),
        FieldMetadata("kind", "string", None, "Pandapower element table kind", "dataset_name"),
        FieldMetadata("index", _index_type(table.index), None, "Pandapower table index", f"net.{table_name}.index"),
        FieldMetadata("alias", "string", None, "Readable pandapower element alias", "pandapower_index"),
    ]
    fields.extend(
        FieldMetadata(
            str(column),
            _dtype_name(table[column].dtype),
            _unit_for(str(column)),
            f"Pandapower {table_name}.{column} field",
            f"net.{table_name}.{column}",
            bool(table[column].isna().any()),
        )
        for column in table.columns
    )
    return [field.as_dict() for field in fields]


def _is_static_table(name: object, table: object) -> bool:
    text = str(name)
    return (
        isinstance(table, pd.DataFrame)
        and not text.startswith("_")
        and not text.startswith("res_")
        and text not in EXCLUDED_NETWORK_TABLES
    )


def _table_name(dataset: str) -> str | None:
    if not dataset.startswith("network.") or dataset in DATASET_FIELDS:
        return None
    name = dataset.removeprefix("network.")
    return name if name and name.replace("_", "").isalnum() else None


def _table_row(table_name: str, revision_ref: str, index: Any, row: pd.Series) -> dict[str, Any]:
    normalized_index = _normalize_scalar(index)
    return {
        "asset_ref": asset_ref(revision_ref, table_name, normalized_index),
        "kind": table_name,
        "index": normalized_index,
        "alias": f"pandapower:{table_name}:{normalized_index}",
        **{str(column): _normalize_scalar(value) for column, value in row.items()},
    }


def _normalize_scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_scalar(item) for key, item in value.items()}
    if hasattr(value, "item"):
        return _normalize_scalar(value.item())
    if pd.isna(value):
        return None
    raise ValueError(f"unsupported non-scalar value in {type(value).__name__}")


def _dtype_name(dtype: Any) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_numeric_dtype(dtype):
        return "number"
    return "string"


def _index_type(index: pd.Index) -> str:
    return "integer" if pd.api.types.is_integer_dtype(index.dtype) else "string"


def _unit_for(field: str) -> str | None:
    units = (
        ("_mvar", "Mvar"),
        ("_mw", "MW"),
        ("_mva", "MVA"),
        ("_kvar", "kvar"),
        ("_kv", "kV"),
        ("_ka", "kA"),
        ("_ohm_per_km", "ohm/km"),
        ("_ohm", "ohm"),
        ("_siemens_per_km", "S/km"),
        ("_degree", "degree"),
        ("_percent", "percent"),
        ("_km", "km"),
        ("_hz", "Hz"),
        ("_celsius", "degree C"),
        ("_s", "s"),
        ("_pu", "p.u."),
    )
    return next((unit for suffix, unit in units if field.endswith(suffix)), None)


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
        return "name" in row and str(row["name"]) == identifier
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
