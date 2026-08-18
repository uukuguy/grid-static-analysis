from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator import evidence


def test_endpoint_evidence_is_persisted_before_success(grid, context_ref: str) -> None:
    response = grid.call(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )
    evidence_ref = response["evidence_ref"]

    loaded = grid.call("evidence.get", {"evidence_ref": evidence_ref})

    assert loaded["evidence_ref"] == evidence_ref
    assert loaded["document"]["evidence_type"] == "network_fact"
    assert loaded["document"]["capability_id"] == "topology.branch.endpoints.get"
    assert loaded["document"]["context_ref"] == context_ref
    assert loaded["document"]["subject_ref"] == response["branch"]["asset_ref"]
    assert loaded["document"]["facts"] == {
        "from_bus_ref": response["from_bus"]["asset_ref"],
        "to_bus_ref": response["to_bus"]["asset_ref"],
    }
    assert loaded["document"]["provenance"]["source_alias"] == "pandapower:line:11"


def test_endpoint_evidence_persistence_failure_returns_no_success(
    monkeypatch: pytest.MonkeyPatch, grid, context_ref: str
) -> None:
    def fail_write(path: Path, document: object) -> None:
        if "network-fact" in path.name:
            raise OSError("injected persistence failure")
        evidence.write_json(path, document)

    monkeypatch.setattr("grid_simulator.operations.write_json", fail_write)

    error = grid.call_error(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )

    assert error.code == "evidence_persist_failed"
    assert error.phase == "persist"
    assert not list((grid.workspace.root / "evidence" / "network-facts").glob("*.json"))


def test_evidence_get_unknown_ref_returns_typed_error(grid) -> None:
    error = grid.call_error("evidence.get", {"evidence_ref": "evidence:sha256:" + "0" * 64})

    assert error.code == "unknown_evidence"
    assert error.phase == "resolve"
