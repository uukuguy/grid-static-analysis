from __future__ import annotations


def _open(grid, model: str) -> str:
    return str(grid.call("context.open", {"model_id": model})["context_ref"])


def _run(grid, context_ref: str, operation: str, options: dict) -> dict:
    return grid.call(
        "analysis.run",
        {"context_ref": context_ref, "operation": operation, "options": options},
    )


def test_topology_path_neighbors_and_unsupplied_are_queryable_analysis_results(grid) -> None:
    context_ref = _open(grid, "case9")
    path = _run(grid, context_ref, "topology.path", {"source_bus": 0, "target_bus": 8})
    neighbors = _run(grid, context_ref, "topology.neighbors", {"source_bus": 0, "max_depth": 2})
    unsupplied = _run(grid, context_ref, "topology.unsupplied", {})

    path_rows = grid.call(
        "result.dataset.query",
        {
            "result_ref": path["result_ref"],
            "dataset": "result.res_topology_path",
            "select": ["order", "bus_index", "bus_ref"],
            "limit": 100,
        },
    )["rows"]
    assert path["summary"]["hop_count"] == len(path_rows) - 1
    assert path_rows[0]["bus_index"] == 0
    assert path_rows[-1]["bus_index"] == 8
    assert neighbors["summary"]["bus_count"] >= 2
    assert unsupplied["summary"]["unsupplied_bus_count"] == 0


def test_result_violations_and_risk_use_matching_model_constraints(grid) -> None:
    base = _open(grid, "case9")
    constrained = grid.call(
        "model.revision.derive",
        {
            "context_ref": base,
            "patches": [
                {
                    "operation": "set",
                    "kind": "bus",
                    "selector": {"where": {}},
                    "values": {"min_vm_pu": 0.8, "max_vm_pu": 0.9},
                },
                {
                    "operation": "set",
                    "kind": "line",
                    "selector": {"where": {}},
                    "values": {"max_loading_percent": 1.0},
                },
            ],
        },
    )
    powerflow = _run(grid, str(constrained["context_ref"]), "powerflow.ac", {})
    violations = grid.call(
        "analysis.result.violations.evaluate", {"result_ref": powerflow["result_ref"]}
    )
    risk = grid.call(
        "analysis.result.risk.rank",
        {"result_ref": violations["result_ref"], "limit": 5},
    )

    assert violations["source_result_ref"] == powerflow["result_ref"]
    assert violations["summary"]["constraint_source"] == "model"
    assert violations["summary"]["violation_count"] > 0
    assert risk["source_result_ref"] == violations["result_ref"]
    assert risk["rankings"]
    assert [row["rank"] for row in risk["rankings"]] == list(range(1, len(risk["rankings"]) + 1))


def test_grid_equivalent_is_an_immutable_revision_with_parent_lineage(grid) -> None:
    context_ref = _open(grid, "case9")
    buses = grid.call(
        "model.dataset.query",
        {
            "context_ref": context_ref,
            "dataset": "network.bus",
            "select": ["index", "asset_ref"],
            "limit": 100,
        },
    )["rows"]
    refs = {row["index"]: row["asset_ref"] for row in buses}
    equivalent = grid.call(
        "model.equivalent.derive",
        {
            "context_ref": context_ref,
            "equivalent_type": "ward",
            "boundary_bus_refs": [refs[index] for index in (3, 5, 7)],
            "internal_bus_refs": [refs[index] for index in (0, 1, 2)],
        },
    )

    assert equivalent["parent_context_ref"] == context_ref
    assert equivalent["context_ref"] != context_ref
    assert equivalent["revision_ref"].startswith("revision:sha256:")
    assert equivalent["lineage_ref"].startswith("lineage:sha256:")
    assert equivalent["counts"]["buses"] < len(buses)


def test_static_fuse_protection_is_constructible_and_queryable(grid) -> None:
    created = grid.call(
        "model.create",
        {
            "name": "static-fuse",
            "elements": [
                {"id": "b0", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                {"id": "b1", "creator": "bus", "arguments": {"vn_kv": 20.0}},
                {"id": "source", "creator": "ext_grid", "arguments": {"bus": {"element_ref": "b0"}}},
                {
                    "id": "line",
                    "creator": "line_from_parameters",
                    "arguments": {
                        "from_bus": {"element_ref": "b0"},
                        "to_bus": {"element_ref": "b1"},
                        "length_km": 1.0,
                        "r_ohm_per_km": 0.1,
                        "x_ohm_per_km": 0.1,
                        "c_nf_per_km": 0.0,
                        "max_i_ka": 1.0,
                    },
                },
                {
                    "id": "switch",
                    "creator": "switch",
                    "arguments": {
                        "bus": {"element_ref": "b0"},
                        "element": {"element_ref": "line"},
                        "et": "l",
                    },
                },
                {
                    "id": "load",
                    "creator": "load",
                    "arguments": {"bus": {"element_ref": "b1"}, "p_mw": 0.1, "q_mvar": 0.02},
                },
                {
                    "id": "fuse",
                    "creator": "protection_fuse",
                    "arguments": {
                        "switch_index": {"element_ref": "switch"},
                        "fuse_type": "HV 100A",
                    },
                },
            ],
        },
    )
    result = _run(grid, str(created["context_ref"]), "protection.static", {"scenario": "pp"})
    rows = grid.call(
        "result.dataset.query",
        {
            "result_ref": result["result_ref"],
            "dataset": "result.res_protection",
            "select": ["switch_id", "protection_type", "trip_melt"],
            "limit": 20,
        },
    )["rows"]

    assert result["summary"]["device_count"] == 1
    assert rows == [{"switch_id": 0, "protection_type": "Fuse", "trip_melt": False}]


def test_n_minus_one_supports_dc_evaluation(grid, context_ref: str, line_refs: list[str]) -> None:
    contingency = grid.call(
        "analysis.contingency.n_minus_one.run",
        {"context_ref": context_ref, "branch_refs": [line_refs[0]], "analysis_method": "dc"},
    )

    assert contingency["solver"]["method"] == "dc"
    assert contingency["scenarios"][0]["status"] == "succeeded"
