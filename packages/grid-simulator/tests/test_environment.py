from __future__ import annotations


def test_environment_distinguishes_future_capability_families(grid) -> None:
    result = grid.call("environment.describe", {})

    families = {item["id"]: item["availability"] for item in result["capability_families"]}
    assert families["power-flow"] == "published"
    assert families["contingency"] == "published"
    assert families["opf"] == "not_published"
    assert families["short-circuit"] == "not_published"
    assert families["state-estimation"] == "not_published"
    assert families["time-series"] == "not_published"
    assert families["model-lifecycle"] == "published"


def test_environment_exposes_contract_context_effects(grid) -> None:
    result = grid.call("environment.describe", {})

    by_id = {item["id"]: item for item in result["executable_capabilities"]}
    powerflow = by_id["analysis.powerflow.ac.run"]
    assert powerflow["availability"] == "published"
    assert powerflow["context_effect"]["projector"] == "powerflow-ac-v1"
    assert powerflow["context_effect"]["produces_state"] == ["calculations.powerflow"]
