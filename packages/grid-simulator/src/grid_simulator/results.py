from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from grid_simulator.analysis_registry import AnalysisOutcome
from grid_simulator.evidence import canonical_json, fingerprint, write_json
from grid_simulator.models import OpenedContext
from grid_simulator.queries import asset_ref
from grid_simulator.workspace import SimulatorWorkspace


_RESULT_REF = re.compile(r"^result:sha256:([0-9a-f]{64})$")
_SUFFIXES = ("_3ph", "_sc", "_est")
_FILTER_OPERATORS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in"})


class UnknownStoredResultError(ValueError):
    pass


class StoredResultIntegrityError(ValueError):
    pass


class UnknownResultDatasetError(ValueError):
    def __init__(self, dataset: str, allowed: list[str]) -> None:
        super().__init__(dataset)
        self.dataset = dataset
        self.allowed = allowed


class ResultFieldError(ValueError):
    def __init__(self, fields: list[str], allowed: list[str]) -> None:
        super().__init__(str(fields))
        self.fields = fields
        self.allowed = allowed


class ResultQueryError(ValueError):
    pass


@dataclass(frozen=True)
class PersistedAnalysis:
    result_ref: str
    evidence_ref: str
    document: dict[str, Any]


class ResultStore:
    def __init__(self, workspace: SimulatorWorkspace) -> None:
        self.workspace = workspace

    def persist(
        self,
        *,
        context: OpenedContext,
        engine: Any,
        net: Any,
        outcome: AnalysisOutcome,
        capability_id: str = "analysis.run",
        evidence_type: str = "analysis_result",
        evidence_subject_ref: str | None = None,
        extra_document: dict[str, Any] | None = None,
        evidence_facts: dict[str, Any] | None = None,
    ) -> PersistedAnalysis:
        datasets = _capture_datasets(net, context.revision_ref)
        document = {
            "result_type": "analysis.operation",
            "operation": outcome.operation,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "engine": engine.name,
            "engine_version": engine.version,
            "status": outcome.status,
            "effective_options": outcome.effective_options,
            "metadata": outcome.metadata,
            "datasets": datasets,
        }
        if extra_document:
            collisions = sorted(set(document) & set(extra_document))
            if collisions:
                raise StoredResultIntegrityError(f"extra result fields collide with identity fields: {collisions}")
            document.update(extra_document)
        digest = fingerprint(canonical_json(document))
        result_ref = f"result:sha256:{digest}"
        persisted = {"result_ref": result_ref, **document}
        write_json(self.workspace.result_document("result", digest), persisted)
        evidence = {
            "evidence_type": evidence_type,
            "capability_id": capability_id,
            "operation": outcome.operation,
            "context_ref": context.context_ref,
            "revision_ref": context.revision_ref,
            "result_ref": result_ref,
            "facts": {
                "status": outcome.status,
                "summary": outcome.metadata,
                "datasets": [
                    {"dataset": name, "row_count": data["row_count"]}
                    for name, data in datasets.items()
                ],
            },
            "provenance": {"engine": engine.name, "engine_version": engine.version},
        }
        if evidence_subject_ref is not None:
            evidence["subject_ref"] = evidence_subject_ref
        if evidence_facts:
            evidence["facts"].update(evidence_facts)
        evidence_digest = fingerprint(canonical_json(evidence))
        evidence_ref = f"evidence:sha256:{evidence_digest}"
        write_json(
            self.workspace.root / "evidence" / "analysis" / f"analysis-evidence-{evidence_digest}.json",
            evidence,
        )
        return PersistedAnalysis(result_ref=result_ref, evidence_ref=evidence_ref, document=persisted)

    def load(self, result_ref: str) -> dict[str, Any]:
        match = _RESULT_REF.fullmatch(result_ref)
        if match is None:
            raise UnknownStoredResultError("result reference is malformed")
        path = self.workspace.result_document("result", match.group(1))
        if not path.is_file():
            raise UnknownStoredResultError("result is unavailable in this workspace")
        try:
            payload = path.read_text(encoding="utf-8")
            document = json.loads(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoredResultIntegrityError("result document is not valid UTF-8 JSON") from exc
        if not isinstance(document, dict) or document.get("result_ref") != result_ref:
            raise StoredResultIntegrityError("result document reference is invalid")
        body = {key: value for key, value in document.items() if key != "result_ref"}
        try:
            digest = fingerprint(canonical_json(body))
        except (TypeError, ValueError) as exc:
            raise StoredResultIntegrityError("result document is not canonical JSON") from exc
        if result_ref != f"result:sha256:{digest}":
            raise StoredResultIntegrityError("result document content does not match its reference")
        if document.get("result_type") != "analysis.operation" or not isinstance(document.get("datasets"), dict):
            raise StoredResultIntegrityError("result document has an unsupported structure")
        return document

    def list_datasets(self, result_ref: str) -> dict[str, Any]:
        document = self.load(result_ref)
        return {
            "result_ref": result_ref,
            "context_ref": document["context_ref"],
            "revision_ref": document["revision_ref"],
            "operation": document["operation"],
            "datasets": [
                {
                    "dataset": name,
                    "dataset_ref": _dataset_ref(result_ref, name),
                    "source_table": data["source_table"],
                    "row_count": data["row_count"],
                }
                for name, data in document["datasets"].items()
            ],
        }

    def describe(self, result_ref: str, dataset: str) -> dict[str, Any]:
        document, data = self._dataset(result_ref, dataset)
        return {
            "result_ref": result_ref,
            "context_ref": document["context_ref"],
            "revision_ref": document["revision_ref"],
            "dataset": dataset,
            "dataset_ref": _dataset_ref(result_ref, dataset),
            "source_table": data["source_table"],
            "row_count": data["row_count"],
            "fields": data["fields"],
        }

    def query(self, result_ref: str, request: dict[str, Any]) -> dict[str, Any]:
        dataset = str(request["dataset"])
        document, data = self._dataset(result_ref, dataset)
        rows = list(data["rows"])
        allowed = [str(field["name"]) for field in data["fields"]]
        select = [str(item) for item in request["select"]]
        _require_fields(select, allowed)
        rows = _filter_rows(rows, dict(request.get("where", {})), list(request.get("filters", [])), allowed)
        sort = request.get("sort")
        if sort is not None:
            field = str(sort["field"])
            _require_fields([field], allowed)
            rows = sorted(
                rows,
                key=lambda row: _sort_key(row.get(field)),
                reverse=str(sort["direction"]) == "descending",
            )
        selected = [{field: row.get(field) for field in select} for row in rows]
        offset = int(request.get("offset", 0))
        limit = min(int(request.get("limit", 100)), 100)
        page = selected[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(selected) else None
        return {
            "result_ref": result_ref,
            "context_ref": document["context_ref"],
            "revision_ref": document["revision_ref"],
            "dataset": dataset,
            "dataset_ref": _dataset_ref(result_ref, dataset),
            "row_count": len(selected),
            "returned_row_count": len(page),
            "offset": offset,
            "next_offset": next_offset,
            "rows": page,
        }

    def aggregate(self, result_ref: str, request: dict[str, Any]) -> dict[str, Any]:
        dataset = str(request["dataset"])
        document, data = self._dataset(result_ref, dataset)
        allowed = [str(field["name"]) for field in data["fields"]]
        group_by = [str(field) for field in request.get("group_by", [])]
        metrics = list(request["metrics"])
        _require_fields(group_by + [str(metric["field"]) for metric in metrics], allowed)
        rows = _filter_rows(list(data["rows"]), dict(request.get("where", {})), [], allowed)
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(tuple(row.get(field) for field in group_by), []).append(row)
        if not groups and not group_by:
            groups[()] = []
        output = []
        for key, group_rows in groups.items():
            result = {field: value for field, value in zip(group_by, key, strict=True)}
            for metric in metrics:
                field = str(metric["field"])
                operation = str(metric["operation"])
                alias = str(metric["alias"])
                result[alias] = _aggregate(group_rows, field, operation)
            output.append(result)
        limit = min(int(request.get("limit", 100)), 100)
        return {
            "result_ref": result_ref,
            "context_ref": document["context_ref"],
            "revision_ref": document["revision_ref"],
            "dataset": dataset,
            "group_by": group_by,
            "group_count": len(output),
            "returned_group_count": min(len(output), limit),
            "rows": output[:limit],
        }

    def compare(self, request: dict[str, Any]) -> dict[str, Any]:
        base_ref = str(request["base_result_ref"])
        candidate_ref = str(request["candidate_result_ref"])
        dataset = str(request["dataset"])
        base_document, base_data = self._dataset(base_ref, dataset)
        candidate_document, candidate_data = self._dataset(candidate_ref, dataset)
        base_allowed = [str(item["name"]) for item in base_data["fields"]]
        candidate_allowed = [str(item["name"]) for item in candidate_data["fields"]]
        key_fields = [str(field) for field in request.get("key_fields", ["index"])]
        fields = [str(field) for field in request["fields"]]
        _require_fields(key_fields + fields, base_allowed)
        _require_fields(key_fields + fields, candidate_allowed)
        base_rows = _filter_rows(list(base_data["rows"]), dict(request.get("where", {})), [], base_allowed)
        base_by_key = {_row_key(row, key_fields): row for row in base_rows}
        candidate_by_key = {_row_key(row, key_fields): row for row in candidate_data["rows"]}
        rows = []
        for key in sorted(set(base_by_key) & set(candidate_by_key), key=repr):
            base_row = base_by_key[key]
            candidate_row = candidate_by_key[key]
            values = {}
            for field in fields:
                base_value = base_row.get(field)
                candidate_value = candidate_row.get(field)
                delta = (
                    float(candidate_value) - float(base_value)
                    if _is_number(base_value) and _is_number(candidate_value)
                    else None
                )
                values[field] = {"base": base_value, "candidate": candidate_value, "delta": delta}
            rows.append({"key": dict(zip(key_fields, key, strict=True)), "values": values})
        limit = min(int(request.get("limit", 100)), 100)
        return {
            "base_result_ref": base_ref,
            "candidate_result_ref": candidate_ref,
            "base_context_ref": base_document["context_ref"],
            "candidate_context_ref": candidate_document["context_ref"],
            "dataset": dataset,
            "key_fields": key_fields,
            "fields": fields,
            "matched_row_count": len(rows),
            "rows": rows[:limit],
        }

    def _dataset(self, result_ref: str, dataset: str) -> tuple[dict[str, Any], dict[str, Any]]:
        document = self.load(result_ref)
        data = document["datasets"].get(dataset)
        if not isinstance(data, dict):
            raise UnknownResultDatasetError(dataset, sorted(document["datasets"]))
        return document, data


def _capture_datasets(net: Any, revision_ref: str) -> dict[str, Any]:
    captured = {}
    for source_table in sorted(key for key in net.keys() if str(key).startswith("res_")):
        table = net[source_table]
        if not isinstance(table, pd.DataFrame) or not len(table.columns):
            continue
        element_kind = _element_kind(net, str(source_table))
        rows = []
        for raw_index, series in table.iterrows():
            index = _json_value(raw_index)
            row = {"index": index}
            if element_kind is not None and raw_index in net[element_kind].index:
                row["asset_ref"] = asset_ref(revision_ref, element_kind, int(raw_index))
            row.update({str(field): _json_value(value) for field, value in series.items()})
            rows.append(row)
        fields = _field_descriptions(str(source_table), table, rows, element_kind is not None)
        dataset = f"result.{source_table}"
        captured[dataset] = {
            "source_table": str(source_table),
            "row_count": len(rows),
            "fields": fields,
            "rows": rows,
        }
    return captured


def _element_kind(net: Any, source_table: str) -> str | None:
    candidate = source_table.removeprefix("res_")
    for suffix in _SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate[: -len(suffix)]
            break
    table = net.get(candidate)
    return candidate if isinstance(table, pd.DataFrame) else None


def _field_descriptions(
    source_table: str, table: pd.DataFrame, rows: list[dict[str, Any]], has_asset_ref: bool
) -> list[dict[str, Any]]:
    names = ["index"] + (["asset_ref"] if has_asset_ref else []) + [str(column) for column in table.columns]
    descriptions = []
    for name in names:
        values = [row.get(name) for row in rows]
        descriptions.append(
            {
                "name": name,
                "type": _field_type(values, name),
                "unit": _unit(name),
                "meaning": "stable source element reference" if name == "asset_ref" else f"pandapower {source_table}.{name}",
                "nullable": any(value is None for value in values),
                "provenance": f"pandapower.{source_table}.{name}",
            }
        )
    return descriptions


def _field_type(values: list[Any], name: str) -> str:
    non_null = [value for value in values if value is not None]
    if name == "asset_ref":
        return "string"
    if not non_null:
        return "number"
    if all(isinstance(value, bool) for value in non_null):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
        return "integer"
    if all(_is_number(value) for value in non_null):
        return "number"
    return "string"


def _unit(field: str) -> str | None:
    suffixes = {
        "_mw": "MW", "_mvar": "Mvar", "_ka": "kA", "_kv": "kV", "_pu": "p.u.",
        "_percent": "percent", "_degree": "degree", "_ohm": "ohm", "_hz": "Hz", "_s": "s",
    }
    return next((unit for suffix, unit in suffixes.items() if field.endswith(suffix)), None)


def _dataset_ref(result_ref: str, dataset: str) -> str:
    return f"dataset:{dataset}:sha256:{fingerprint(canonical_json({'result_ref': result_ref, 'dataset': dataset}))}"


def _require_fields(fields: list[str], allowed: list[str]) -> None:
    missing = sorted(set(fields) - set(allowed))
    if missing:
        raise ResultFieldError(missing, allowed)


def _filter_rows(
    rows: list[dict[str, Any]], where: dict[str, Any], filters: list[dict[str, Any]], allowed: list[str]
) -> list[dict[str, Any]]:
    _require_fields([str(field) for field in where], allowed)
    for item in filters:
        _require_fields([str(item["field"])], allowed)
        if str(item["operator"]) not in _FILTER_OPERATORS:
            raise ResultQueryError("filter operator is unavailable")
    selected = []
    for row in rows:
        if any(row.get(str(field)) != value for field, value in where.items()):
            continue
        if all(_matches(row.get(str(item["field"])), str(item["operator"]), item.get("value")) for item in filters):
            selected.append(row)
    return selected


def _matches(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return actual in expected if isinstance(expected, list) else False
    if actual is None or expected is None:
        return False
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    return False


def _aggregate(rows: list[dict[str, Any]], field: str, operation: str) -> int | float | None:
    if operation == "count":
        return len(rows)
    values = [float(row[field]) for row in rows if _is_number(row.get(field))]
    if not values:
        return None
    if operation == "sum":
        return float(sum(values))
    if operation == "min":
        return float(min(values))
    if operation == "max":
        return float(max(values))
    if operation == "avg":
        return float(sum(values) / len(values))
    raise ResultQueryError("aggregate operation is unavailable")


def _row_key(row: dict[str, Any], fields: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(field) for field in fields)


def _sort_key(value: Any) -> tuple[bool, str, Any]:
    return (value is None, type(value).__name__, value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, str):
        return value
    raise StoredResultIntegrityError(f"result value of type {type(value).__name__} cannot cross the boundary")
