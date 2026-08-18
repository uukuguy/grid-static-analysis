from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator.engine import Pandapower340Engine
from grid_simulator.models import ContextStore, ModelNotFoundError, ModelRegistry
from grid_simulator.workspace import SimulatorWorkspace


def test_registry_lists_ieee39_with_domain_aliases() -> None:
    model = ModelRegistry(Pandapower340Engine()).list()[0]

    assert model.model_id == "ieee39"
    assert "IEEE-39节点系统" in model.aliases
    assert model.source == "pandapower.networks.case39"
    assert model.engine == "pandapower"
    assert model.engine_version == "3.4.0"


def test_registry_lists_the_versioned_pandapower_network_catalog() -> None:
    models = ModelRegistry(Pandapower340Engine()).list()
    by_id = {model.model_id: model for model in models}

    assert len(models) >= 50
    assert {"ieee39", "case9", "case14", "create_cigre_network_mv"} <= set(by_id)
    assert by_id["case9"].source == "pandapower.networks.case9"
    assert by_id["create_cigre_network_mv"].source == "pandapower.networks.create_cigre_network_mv"
    assert len({model.source for model in models}) == len(models)


@pytest.mark.parametrize(
    ("model_id", "expected_buses"),
    [("case9", 9), ("case14", 14), ("ieee39", 39)],
)
def test_registry_opens_multiple_allowlisted_networks(model_id: str, expected_buses: int) -> None:
    model, net = ModelRegistry(Pandapower340Engine()).open(model_id)

    assert model.model_id == model_id
    assert len(net.bus) == expected_buses


def test_registry_opens_specialized_packaged_network() -> None:
    model, net = ModelRegistry(Pandapower340Engine()).open("create_cigre_network_mv")

    assert model.source == "pandapower.networks.create_cigre_network_mv"
    assert len(net.bus) > 0
    assert len(net.line) > 0


def test_open_context_persists_immutable_revision(tmp_path: Path) -> None:
    workspace = SimulatorWorkspace(tmp_path)
    context = ContextStore(workspace, ModelRegistry(Pandapower340Engine())).create("ieee39")
    loaded = ContextStore(workspace, ModelRegistry(Pandapower340Engine())).require(context.context_ref)

    assert loaded == context
    assert context.revision_ref.startswith("revision:sha256:")
    assert workspace.model_artifact(context.revision_ref).is_file()


def test_context_revision_matches_registry_trusted_revision(tmp_path: Path) -> None:
    engine = Pandapower340Engine()
    registry = ModelRegistry(engine)
    context = ContextStore(SimulatorWorkspace(tmp_path), registry).create("ieee39")

    assert context.revision_ref == registry.trusted_revision_ref("ieee39")


def test_reopening_registered_model_keeps_same_context_and_revision(tmp_path: Path) -> None:
    store = ContextStore(SimulatorWorkspace(tmp_path), ModelRegistry(Pandapower340Engine()))

    first = store.create("ieee39")
    second = store.create("ieee39")

    assert second == first


def test_registry_rejects_arbitrary_model_ids_without_callable_resolution() -> None:
    registry = ModelRegistry(Pandapower340Engine())

    with pytest.raises(ModelNotFoundError):
        registry.open("pandapower.networks.case118")

    with pytest.raises(ModelNotFoundError):
        registry.open("pp_elements")
