from __future__ import annotations


def test_line_11_returns_endpoints_without_powerflow(grid, context_ref: str) -> None:
    response = grid.call(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )

    assert response["branch"]["alias"] == "pandapower:line:11"
    assert response["from_bus"]["name"] == "6"
    assert response["to_bus"]["name"] == "11"
    assert response["evidence_ref"].startswith("evidence:sha256:")
    assert not list(grid.workspace.results_dir.glob("powerflow-*.json"))


def test_branch_endpoints_accepts_asset_ref(grid, context_ref: str) -> None:
    resolved = grid.call(
        "model.element.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )
    response = grid.call(
        "topology.branch.endpoints.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "asset_ref", "identifier": resolved["asset_ref"]},
    )

    assert response["branch"]["asset_ref"] == resolved["asset_ref"]
    assert response["from_bus"]["asset_ref"] == resolved["element"]["from_bus_ref"]
    assert response["to_bus"]["asset_ref"] == resolved["element"]["to_bus_ref"]


def test_components_return_bounded_bus_refs_without_powerflow(grid, context_ref: str) -> None:
    response = grid.call("topology.components.get", {"context_ref": context_ref})

    assert response["component_count"] == 1
    assert response["components"][0]["component_id"] == "component:0"
    assert response["components"][0]["bus_count"] == 39
    assert response["components"][0]["branch_count"] == 46
    assert len(response["components"][0]["bus_refs"]) == 39
    assert all(item.startswith("asset:bus:sha256:") for item in response["components"][0]["bus_refs"])
    assert not list(grid.workspace.results_dir.glob("powerflow-*.json"))
