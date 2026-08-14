from __future__ import annotations

import copy

import pytest

from grid_agent.analysis.capabilities import CapabilityContextCatalog, CapabilityContextError


def test_context_catalog_loads_contract_selected_projector(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    catalog = CapabilityContextCatalog.from_documents(capability_documents)

    spec = catalog.require("analysis.powerflow.ac.run")

    assert spec.projector == "powerflow-ac-v1"
    assert spec.result_kind == "powerflow.ac"
    assert spec.produces_state == ("calculations.powerflow",)


def test_context_catalog_rejects_unknown_projector(
    capability_documents: tuple[dict[str, object], ...],
) -> None:
    document = copy.deepcopy(capability_documents[0])
    context_effect = dict(document["context_effect"])
    context_effect["projector"] = "missing-v1"
    document["context_effect"] = context_effect

    with pytest.raises(CapabilityContextError, match="unknown context projector"):
        CapabilityContextCatalog.from_documents((document,))
