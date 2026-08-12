from __future__ import annotations

import json
from importlib.resources import files
from typing import Iterable

from grid_simulator.capabilities.schema import CapabilityContract


class CapabilityRegistry:
    def __init__(self, contracts: Iterable[CapabilityContract]) -> None:
        sorted_contracts = tuple(sorted(contracts, key=lambda contract: contract.id))
        ids = [contract.id for contract in sorted_contracts]
        if len(set(ids)) != len(ids):
            raise ValueError("capability ids must be unique")
        tool_names = [contract.tool_name for contract in sorted_contracts]
        if len(set(tool_names)) != len(tool_names):
            raise ValueError("capability tool names must be unique")
        self._contracts = sorted_contracts
        self._by_id = {contract.id: contract for contract in sorted_contracts}

    @classmethod
    def load_packaged(cls) -> CapabilityRegistry:
        definitions = files("grid_simulator.capabilities.definitions")
        contracts = []
        for resource in sorted(definitions.iterdir(), key=lambda item: item.name):
            if resource.name.endswith(".json") and resource.is_file():
                raw = json.loads(resource.read_text(encoding="utf-8"))
                contracts.append(CapabilityContract.model_validate(raw))
        return cls(contracts)

    def list(self) -> tuple[CapabilityContract, ...]:
        return self._contracts

    def require(self, identifier: str) -> CapabilityContract:
        try:
            return self._by_id[identifier]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {identifier}") from exc
