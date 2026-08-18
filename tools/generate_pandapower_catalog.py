#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandapower
import pandapower.networks as networks


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages/grid-simulator/src/grid_simulator/catalogs/pandapower-networks-3.4.0.json"


def compatible_factories() -> list[dict[str, object]]:
    if pandapower.__version__ != "3.4.0":
        raise RuntimeError(f"catalog generation requires pandapower 3.4.0, got {pandapower.__version__}")
    rows: list[dict[str, object]] = []
    for name in sorted(dir(networks)):
        if name.startswith("_") or name == "case39":
            continue
        factory = getattr(networks, name)
        if not inspect.isfunction(factory) or not factory.__module__.startswith("pandapower.networks."):
            continue
        parameters = inspect.signature(factory).parameters.values()
        required = [
            parameter.name
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        ]
        if required:
            continue
        doc = inspect.getdoc(factory) or name
        title = next((line.strip() for line in doc.splitlines() if line.strip()), name)
        rows.append(
            {
                "model_id": name,
                "factory": name,
                "title": title[:200],
                "aliases": [name, f"pandapower.networks.{name}"],
                "source": f"pandapower.networks.{name}",
            }
        )
    ieee39 = {
        "model_id": "ieee39",
        "factory": "case39",
        "title": "IEEE 39-bus system",
        "aliases": [
            "case39",
            "IEEE-39节点系统",
            "IEEE 39 bus system",
            "New England 39-bus system",
            "pandapower.networks.case39",
        ],
        "source": "pandapower.networks.case39",
    }
    return [ieee39, *rows]


def main() -> None:
    document = {
        "schema_version": "1.0",
        "engine": "pandapower",
        "engine_version": "3.4.0",
        "generation_rule": "zero-required-argument functions defined under pandapower.networks.*",
        "models": compatible_factories(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(document['models'])} registered models to {OUTPUT}")


if __name__ == "__main__":
    main()
