from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any


CATALOG_RESOURCE = "catalogs/pandapower-networks-3.4.0.json"


class ModelCatalogError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_model_catalog() -> tuple[dict[str, Any], ...]:
    resource = files("grid_simulator").joinpath(CATALOG_RESOURCE)
    try:
        document = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelCatalogError("packaged model catalog is unreadable") from exc
    if document.get("engine") != "pandapower" or document.get("engine_version") != "3.4.0":
        raise ModelCatalogError("packaged model catalog engine metadata is invalid")
    models = document.get("models")
    if not isinstance(models, list) or not models:
        raise ModelCatalogError("packaged model catalog has no models")
    required = {"model_id", "factory", "title", "aliases", "source"}
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in models:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ModelCatalogError("packaged model catalog row is invalid")
        if raw["model_id"] in seen_ids or raw["source"] in seen_sources:
            raise ModelCatalogError("packaged model catalog contains duplicates")
        if not isinstance(raw["aliases"], list) or not all(isinstance(item, str) for item in raw["aliases"]):
            raise ModelCatalogError("packaged model aliases are invalid")
        seen_ids.add(raw["model_id"])
        seen_sources.add(raw["source"])
        normalized.append(dict(raw))
    return tuple(normalized)


def allowed_network_factories() -> frozenset[str]:
    return frozenset(str(row["factory"]) for row in load_model_catalog())
