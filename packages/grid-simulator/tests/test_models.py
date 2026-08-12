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
