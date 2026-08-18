from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pandapower as pp
from pandapower.toolbox import drop_elements

from grid_simulator.creators import CreatorRegistry
from grid_simulator.evidence import canonical_json, fingerprint, write_json, write_network
from grid_simulator.models import OpenedContext
from grid_simulator.workspace import SimulatorWorkspace


class PatchKindError(ValueError):
    pass


class PatchFieldError(ValueError):
    def __init__(self, kind: str, fields: list[str], allowed: list[str]) -> None:
        super().__init__(kind)
        self.kind = kind
        self.fields = fields
        self.allowed = allowed


class PatchSelectorError(ValueError):
    pass


@dataclass(frozen=True)
class RevisionResult:
    context: OpenedContext
    counts: dict[str, int]


class RevisionStore:
    def __init__(self, workspace: SimulatorWorkspace, engine: Any) -> None:
        self.workspace = workspace
        self.engine = engine

    def create(self, *, name: str, sn_mva: float, f_hz: float, elements: list[dict[str, Any]]) -> RevisionResult:
        net = pp.create_empty_network(name=name, sn_mva=sn_mva, f_hz=f_hz)
        CreatorRegistry().apply_elements(net, elements)
        return self._persist(
            net=net,
            model_id=f"created:{name}",
            origin="created",
            parent_context=None,
            operation={"name": name, "sn_mva": sn_mva, "f_hz": f_hz, "elements": elements},
        )

    def derive(
        self,
        *,
        parent_context: OpenedContext,
        parent_net: Any,
        patches: list[dict[str, Any]],
    ) -> RevisionResult:
        net = copy.deepcopy(parent_net)
        creator_registry = CreatorRegistry()
        local_references: dict[str, Any] = {}
        for patch in patches:
            self._apply_patch(net, patch, creator_registry, local_references)
        return self._persist(
            net=net,
            model_id=parent_context.model_id,
            origin="derived",
            parent_context=parent_context,
            operation={"patches": patches},
        )

    def persist_derived_network(
        self,
        *,
        parent_context: OpenedContext,
        net: Any,
        operation: dict[str, Any],
    ) -> RevisionResult:
        return self._persist(
            net=net,
            model_id=parent_context.model_id,
            origin="derived",
            parent_context=parent_context,
            operation=operation,
        )

    def _apply_patch(
        self,
        net: Any,
        patch: dict[str, Any],
        creator_registry: CreatorRegistry,
        local_references: dict[str, Any],
    ) -> None:
        operation = str(patch["operation"])
        if operation == "create":
            creator_registry.apply_element(net, patch, local_references)
            return
        kind = str(patch["kind"])
        if kind not in net or not isinstance(net[kind], pd.DataFrame):
            raise PatchKindError(kind)
        table = net[kind]
        indices = _select_indices(table, dict(patch.get("selector", {})))
        if operation == "scale":
            fields = [str(field) for field in patch["fields"]]
            _require_fields(kind, table, fields)
            if any(not pd.api.types.is_numeric_dtype(table[field].dtype) for field in fields):
                raise PatchFieldError(kind, fields, list(map(str, table.columns)))
            table.loc[indices, fields] = table.loc[indices, fields] * float(patch["factor"])
            return
        if operation == "set":
            values = dict(patch["values"])
            _require_fields(kind, table, list(map(str, values)))
            for field, value in values.items():
                table.loc[indices, str(field)] = value
            return
        if operation == "in_service":
            _require_fields(kind, table, ["in_service"])
            table.loc[indices, "in_service"] = bool(patch["value"])
            return
        if operation == "switch_state" and kind == "switch":
            _require_fields(kind, table, ["closed"])
            table.loc[indices, "closed"] = bool(patch["closed"])
            return
        if operation == "drop":
            drop_elements(net, kind, indices)
            return
        raise PatchKindError(operation)

    def _persist(
        self,
        *,
        net: Any,
        model_id: str,
        origin: str,
        parent_context: OpenedContext | None,
        operation: dict[str, Any],
    ) -> RevisionResult:
        serialized = self.engine.serialize(net)
        revision_ref = f"revision:sha256:{fingerprint(serialized)}"
        document: dict[str, Any] = {
            "model_id": model_id,
            "revision_ref": revision_ref,
            "engine": self.engine.name,
            "engine_version": self.engine.version,
            "origin": origin,
            "parent_context_ref": parent_context.context_ref if parent_context else None,
        }
        lineage = {
            "revision_ref": revision_ref,
            "model_id": model_id,
            "origin": origin,
            "parent_context_ref": parent_context.context_ref if parent_context else None,
            "parent_revision_ref": parent_context.revision_ref if parent_context else None,
            "engine": self.engine.name,
            "engine_version": self.engine.version,
            "operation": operation,
        }
        lineage_ref = f"lineage:sha256:{fingerprint(canonical_json(lineage))}"
        document["lineage_ref"] = lineage_ref
        context_ref = f"context:sha256:{fingerprint(canonical_json(document))}"
        write_network(self.workspace.model_artifact(revision_ref), serialized)
        write_json(self.workspace.lineage_document(lineage_ref), lineage)
        write_json(self.workspace.context_document(context_ref), document)
        context = OpenedContext(context_ref=context_ref, **document)
        return RevisionResult(context=context, counts=_counts(net))


def _select_indices(table: pd.DataFrame, selector: dict[str, Any]) -> list[Any]:
    if "indices" in selector:
        indices = list(selector["indices"])
        if any(index not in table.index for index in indices):
            raise PatchSelectorError("selector contains unknown indices")
        return indices
    where = dict(selector.get("where", {}))
    _require_fields("selector", table, list(map(str, where)))
    mask = pd.Series(True, index=table.index)
    for field, value in where.items():
        mask &= table[str(field)] == value
    return list(table.index[mask])


def _require_fields(kind: str, table: pd.DataFrame, fields: list[str]) -> None:
    unavailable = [field for field in fields if field not in table.columns]
    if unavailable:
        raise PatchFieldError(kind, unavailable, list(map(str, table.columns)))


def _counts(net: Any) -> dict[str, int]:
    return {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo))}
