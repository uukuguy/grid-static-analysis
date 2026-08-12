from __future__ import annotations


def test_branch_dataset_schema_enumerates_every_queryable_field(grid, context_ref: str) -> None:
    description = grid.call("model.dataset.describe", {"context_ref": context_ref, "dataset": "network.branches"})
    fields = {item["name"] for item in description["fields"]}

    assert {"asset_ref", "kind", "name", "from_bus_ref", "to_bus_ref", "in_service"} <= fields
    assert all({"name", "type", "unit", "meaning", "provenance"} <= set(item) for item in description["fields"])


def test_bus_dataset_query_selects_and_sorts_declared_fields(grid, context_ref: str) -> None:
    response = grid.call(
        "model.dataset.query",
        {
            "context_ref": context_ref,
            "dataset": "network.buses",
            "select": ["name", "vn_kv", "asset_ref"],
            "where": {"name": "6"},
            "sort": {"field": "name", "direction": "ascending"},
            "limit": 5,
        },
    )

    assert response["dataset"] == "network.buses"
    assert response["row_count"] == 1
    assert response["returned_row_count"] == 1
    assert response["rows"] == [{"name": "6", "vn_kv": 345.0, "asset_ref": response["rows"][0]["asset_ref"]}]
    assert response["rows"][0]["asset_ref"].startswith("asset:bus:sha256:")


def test_branch_dataset_query_filters_by_kind_and_asset_ref(grid, context_ref: str) -> None:
    resolved = grid.call(
        "model.element.get",
        {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    )
    response = grid.call(
        "model.dataset.query",
        {
            "context_ref": context_ref,
            "dataset": "network.branches",
            "select": ["asset_ref", "kind", "alias", "from_bus_ref", "to_bus_ref", "in_service"],
            "where": {"asset_ref": resolved["asset_ref"], "kind": "line"},
            "sort": {"field": "alias", "direction": "descending"},
            "limit": 10,
        },
    )

    assert response["row_count"] == 1
    assert response["rows"] == [
        {
            "asset_ref": resolved["asset_ref"],
            "kind": "line",
            "alias": "pandapower:line:11",
            "from_bus_ref": resolved["element"]["from_bus_ref"],
            "to_bus_ref": resolved["element"]["to_bus_ref"],
            "in_service": True,
        }
    ]


def test_unknown_query_field_returns_allowed_fields(grid, context_ref: str) -> None:
    error = grid.call_error(
        "model.dataset.query",
        {"context_ref": context_ref, "dataset": "network.branches", "select": ["mystery"]},
    )

    assert error.code == "field_unavailable"
    assert "allowed_fields" in error.details
    assert error.allowed_recovery_actions == ("describe_dataset",)


def test_sort_field_must_be_selected(grid, context_ref: str) -> None:
    error = grid.call_error(
        "model.dataset.query",
        {
            "context_ref": context_ref,
            "dataset": "network.buses",
            "select": ["name"],
            "sort": {"field": "vn_kv", "direction": "ascending"},
        },
    )

    assert error.code == "sort_field_unselected"
    assert error.allowed_recovery_actions == ("select_sort_field",)
