from __future__ import annotations


def test_ieee39_bus_voltage_constraints_come_from_model(grid, context_ref: str) -> None:
    result = grid.call("model.constraints.describe", {"context_ref": context_ref})

    voltage = next(item for item in result["constraints"] if item["quantity"] == "bus.vm_pu")
    assert voltage["lower"] == 0.94
    assert voltage["upper"] == 1.06
    assert voltage["unit"] == "p.u."
    assert voltage["applies_to_count"] == 39
    assert voltage["source"] == {
        "kind": "model",
        "table": "bus",
        "fields": ["min_vm_pu", "max_vm_pu"],
    }
    assert result["context_ref"] == context_ref
    assert str(result["revision_ref"]).startswith("revision:sha256:")
    assert result["evidence_refs"]


def test_model_constraints_do_not_publish_project_policy(grid, context_ref: str) -> None:
    result = grid.call("model.constraints.describe", {"context_ref": context_ref})

    assert "policy" not in result
    assert all(item["source"]["kind"] == "model" for item in result["constraints"])


def test_model_constraint_evidence_can_be_read_back(grid, context_ref: str) -> None:
    result = grid.call("model.constraints.describe", {"context_ref": context_ref})

    loaded = grid.call("evidence.get", {"evidence_ref": result["evidence_refs"][0]})

    assert loaded["document"]["capability_id"] == "model.constraints.describe"
    assert loaded["document"]["facts"]["constraints"] == result["constraints"]
