from __future__ import annotations


def _run(grid, context_ref: str) -> dict[str, object]:
    return grid.call("analysis.run", {"context_ref": context_ref, "operation": "powerflow.ac", "options": {}})


def test_result_dataset_list_publishes_every_generated_result_table(grid, context_ref: str) -> None:
    analysis = _run(grid, context_ref)
    listed = grid.call("result.dataset.list", {"result_ref": analysis["result_ref"]})
    by_name = {item["dataset"]: item for item in listed["datasets"]}

    assert {"result.res_bus", "result.res_line", "result.res_trafo", "result.res_ext_grid", "result.res_gen", "result.res_load"} <= set(by_name)
    assert by_name["result.res_ext_grid"]["row_count"] == 1
    assert all(item["source_table"].startswith("res_") for item in by_name.values())


def test_dedicated_ac_result_uses_the_same_complete_result_dataset_substrate(grid, context_ref: str) -> None:
    analysis = grid.call("analysis.powerflow.ac.run", {"context_ref": context_ref})

    listed = grid.call("result.dataset.list", {"result_ref": analysis["result_ref"]})

    assert any(item["dataset"] == "result.res_ext_grid" for item in listed["datasets"])


def test_successful_contingency_scenario_persists_its_complete_result_tables(
    grid, context_ref: str, line_refs: list[str]
) -> None:
    contingency = grid.call(
        "analysis.contingency.n_minus_one.run",
        {"context_ref": context_ref, "branch_refs": [line_refs[0]]},
    )
    scenario_ref = contingency["scenarios"][0]["scenario_result_ref"]

    listed = grid.call("result.dataset.list", {"result_ref": scenario_ref})

    assert any(item["dataset"] == "result.res_bus" for item in listed["datasets"])
    assert any(item["dataset"] == "result.res_line" for item in listed["datasets"])


def test_result_dataset_describe_and_query_expose_ext_grid_active_power(grid, context_ref: str) -> None:
    analysis = _run(grid, context_ref)
    result_ref = analysis["result_ref"]
    described = grid.call("result.dataset.describe", {"result_ref": result_ref, "dataset": "result.res_ext_grid"})
    fields = {item["name"]: item for item in described["fields"]}
    assert fields["p_mw"]["unit"] == "MW"
    assert fields["p_mw"]["type"] == "number"

    queried = grid.call(
        "result.dataset.query",
        {
            "result_ref": result_ref,
            "dataset": "result.res_ext_grid",
            "select": ["index", "asset_ref", "p_mw", "q_mvar"],
            "sort": {"field": "index", "direction": "ascending"},
            "limit": 10,
        },
    )
    assert queried["rows"][0]["asset_ref"].startswith("asset:ext_grid:sha256:")
    assert isinstance(queried["rows"][0]["p_mw"], float)


def test_result_dataset_query_rejects_undescribed_field_with_recovery(grid, context_ref: str) -> None:
    analysis = _run(grid, context_ref)
    error = grid.call_error(
        "result.dataset.query",
        {"result_ref": analysis["result_ref"], "dataset": "result.res_bus", "select": ["python"]},
    )

    assert error.code == "result_field_unavailable"
    assert "vm_pu" in error.details["allowed_fields"]


def test_result_query_pages_do_not_truncate_the_persisted_full_table(grid, context_ref: str) -> None:
    analysis = _run(grid, context_ref)
    first = grid.call(
        "result.dataset.query",
        {
            "result_ref": analysis["result_ref"], "dataset": "result.res_bus",
            "select": ["index", "vm_pu"], "offset": 0, "limit": 2,
        },
    )
    second = grid.call(
        "result.dataset.query",
        {
            "result_ref": analysis["result_ref"], "dataset": "result.res_bus",
            "select": ["index", "vm_pu"], "offset": first["next_offset"], "limit": 2,
        },
    )

    assert first["row_count"] == 39
    assert first["returned_row_count"] == 2
    assert second["row_count"] == 39
    assert [row["index"] for row in first["rows"] + second["rows"]] == [0, 1, 2, 3]


def test_result_aggregate_computes_typed_metrics_without_rerunning_analysis(grid, context_ref: str) -> None:
    analysis = _run(grid, context_ref)
    run_count = grid.engine.ac_run_count
    aggregated = grid.call(
        "result.aggregate",
        {
            "result_ref": analysis["result_ref"],
            "dataset": "result.res_load",
            "metrics": [
                {"field": "p_mw", "operation": "sum", "alias": "total_p_mw"},
                {"field": "p_mw", "operation": "max", "alias": "max_p_mw"},
                {"field": "index", "operation": "count", "alias": "load_count"},
            ],
        },
    )

    assert grid.engine.ac_run_count == run_count
    assert aggregated["rows"][0]["total_p_mw"] > 0
    assert aggregated["rows"][0]["max_p_mw"] > 0
    assert aggregated["rows"][0]["load_count"] == 21


def test_result_compare_aligns_rows_across_immutable_revisions(grid, context_ref: str) -> None:
    base = _run(grid, context_ref)
    derived = grid.call(
        "model.revision.derive",
        {
            "context_ref": context_ref,
            "patches": [
                {"operation": "scale", "kind": "load", "selector": {"indices": [0]}, "fields": ["p_mw"], "factor": 1.1}
            ],
        },
    )
    candidate = _run(grid, str(derived["context_ref"]))

    compared = grid.call(
        "result.compare",
        {
            "base_result_ref": base["result_ref"],
            "candidate_result_ref": candidate["result_ref"],
            "dataset": "result.res_load",
            "key_fields": ["index"],
            "fields": ["p_mw"],
            "where": {"index": 0},
            "limit": 10,
        },
    )

    row = compared["rows"][0]
    assert row["key"] == {"index": 0}
    assert row["values"]["p_mw"]["candidate"] > row["values"]["p_mw"]["base"]
    assert row["values"]["p_mw"]["delta"] > 0
