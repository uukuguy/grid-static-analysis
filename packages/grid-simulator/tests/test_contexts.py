from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator.engine import Pandapower340Engine
from grid_simulator.models import ContextIntegrityError, ContextNotFoundError, ContextStore, InvalidContextRef, ModelRegistry
from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest
from grid_simulator.workspace import SimulatorWorkspace


def _request(capability: str, arguments: dict[str, object]) -> GridCapabilityRequest:
    return GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id=f"req-{capability}",
        capability=capability,
        arguments=arguments,
    )


def test_require_rejects_malformed_context_ref(tmp_path: Path) -> None:
    store = ContextStore(SimulatorWorkspace(tmp_path), ModelRegistry(Pandapower340Engine()))

    with pytest.raises(InvalidContextRef):
        store.require("../not-a-context")


def test_require_does_not_implicitly_reopen_missing_context(tmp_path: Path) -> None:
    workspace = SimulatorWorkspace(tmp_path)
    store = ContextStore(workspace, ModelRegistry(Pandapower340Engine()))

    with pytest.raises(ContextNotFoundError):
        store.require("context:sha256:" + "a" * 64)

    assert not workspace.contexts_dir.exists()
    assert not workspace.model_artifacts_dir.exists()


def test_require_detects_tampered_context_document(tmp_path: Path) -> None:
    workspace = SimulatorWorkspace(tmp_path)
    store = ContextStore(workspace, ModelRegistry(Pandapower340Engine()))
    context = store.create("ieee39")
    workspace.context_document(context.context_ref).write_text(
        '{"model_id":"ieee39","revision_ref":"revision:sha256:'
        + "0" * 64
        + '","engine":"pandapower","engine_version":"3.4.0"}',
        encoding="utf-8",
    )

    with pytest.raises(ContextIntegrityError):
        store.require(context.context_ref)


def test_load_network_detects_tampered_model_artifact(tmp_path: Path) -> None:
    workspace = SimulatorWorkspace(tmp_path)
    store = ContextStore(workspace, ModelRegistry(Pandapower340Engine()))
    context = store.create("ieee39")
    workspace.model_artifact(context.revision_ref).write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ContextIntegrityError):
        store.load_network(context.context_ref)


def test_context_get_executes_against_verified_existing_context(tmp_path: Path) -> None:
    opened = dispatch(_request("context.open", {"model": "ieee39"}), tmp_path)
    assert opened.ok is True
    assert opened.result is not None

    fetched = dispatch(_request("context.get", {"context_ref": opened.result["context_ref"]}), tmp_path)

    assert fetched.ok is True
    assert fetched.result == {
        "context_ref": opened.result["context_ref"],
        "model": "ieee39",
        "counts": {"buses": 39, "lines": 35, "transformers": 11},
    }


def test_context_get_missing_ref_is_typed_unknown_context(tmp_path: Path) -> None:
    response = dispatch(_request("context.get", {"context_ref": "context:sha256:" + "a" * 64}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unknown_context"
    assert response.error.phase == "resolve"


def test_context_open_unknown_registered_model_is_operation_error(tmp_path: Path) -> None:
    response = dispatch(_request("context.open", {"model": "case118"}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "model_not_found"
    assert response.error.phase == "resolve"
    assert not (tmp_path / "evidence").exists()
