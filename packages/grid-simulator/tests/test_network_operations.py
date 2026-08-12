from __future__ import annotations

from grid_simulator.protocol import CapabilityError


def test_context_open_rejects_unknown_model_id_at_operation_boundary(grid) -> None:
    error = grid.call_error("context.open", {"model_id": "other"})

    assert error.code == "model_not_found"
    assert error.phase == "resolve"
    assert error.allowed_recovery_actions == ("call_model_list",)


def test_model_element_get_resolves_line_by_pandapower_index(grid, context_ref: str) -> None:
    response = grid.call(
        "model.element.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )

    assert response["asset_ref"].startswith("asset:line:sha256:")
    assert response["element"]["kind"] == "line"
    assert response["element"]["alias"] == "pandapower:line:11"
    assert response["element"]["name"] == "11"
    assert response["element"]["from_bus_ref"].startswith("asset:bus:sha256:")
    assert response["element"]["to_bus_ref"].startswith("asset:bus:sha256:")


def test_model_element_get_resolves_bus_by_name(grid, context_ref: str) -> None:
    response = grid.call(
        "model.element.get",
        {"context_ref": context_ref, "kind": "bus", "namespace": "name", "identifier": "6"},
    )

    assert response["asset_ref"].startswith("asset:bus:sha256:")
    assert response["element"] == {
        "asset_ref": response["asset_ref"],
        "kind": "bus",
        "index": 5,
        "name": "6",
        "alias": "pandapower:bus:5",
        "vn_kv": 345.0,
        "in_service": True,
    }


def test_model_element_get_unknown_line_is_typed_error(grid, context_ref: str) -> None:
    error: CapabilityError = grid.call_error(
        "model.element.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "171"},
    )

    assert error.code == "unknown_element"
    assert error.phase == "resolve"
    assert error.allowed_recovery_actions == ("query_dataset",)
