from __future__ import annotations

import pytest


EXPECTED_OPERATIONS = {
    "powerflow.ac",
    "powerflow.dc",
    "powerflow.three_phase",
    "opf.ac",
    "opf.dc",
    "short_circuit.iec60909",
    "state_estimation.estimate",
    "state_estimation.chi2",
    "state_estimation.remove_bad_data",
    "diagnostic.run",
}


def _open(grid, model_id: str) -> str:
    return str(grid.call("context.open", {"model_id": model_id})["context_ref"])


def _run(grid, context_ref: str, operation: str, options: dict | None = None) -> dict:
    return grid.call(
        "analysis.run",
        {"context_ref": context_ref, "operation": operation, "options": options or {}},
    )


def _dataset_names(grid, result_ref: str) -> set[str]:
    listed = grid.call("result.dataset.list", {"result_ref": result_ref})
    return {str(item["dataset"]) for item in listed["datasets"]}


def test_registry_publishes_every_native_static_analysis_with_closed_options(grid) -> None:
    listed = grid.call("analysis.operation.list", {})
    assert {item["id"] for item in listed["operations"]} == EXPECTED_OPERATIONS

    expected_options = {
        "powerflow.ac": {"algorithm", "max_iteration", "distributed_slack", "tdpf"},
        "powerflow.dc": {"trafo_model", "switch_rx_ratio", "trafo3w_losses"},
        "powerflow.three_phase": {"calculate_voltage_angles", "max_iteration", "switch_rx_ratio"},
        "opf.ac": {"calculate_voltage_angles", "init", "delta", "consider_line_temperature"},
        "opf.dc": {"check_connectivity", "switch_rx_ratio", "delta"},
        "short_circuit.iec60909": {"bus", "fault", "case", "ip", "ith", "branch_results"},
        "state_estimation.estimate": {"algorithm", "init", "zero_injection", "debug_mode"},
        "state_estimation.chi2": {"init", "chi2_prob_false"},
        "state_estimation.remove_bad_data": {"init", "rn_max_threshold"},
        "diagnostic.run": {"warnings_only", "overload_scaling_factor", "nom_voltage_tolerance"},
    }
    for operation, required in expected_options.items():
        described = grid.call("analysis.operation.describe", {"operation": operation})
        schema = described["options_schema"]
        assert schema["additionalProperties"] is False
        assert required <= set(schema["properties"])


def test_dc_powerflow_captures_native_result_tables(grid) -> None:
    analysis = _run(grid, _open(grid, "case9"), "powerflow.dc", {"trafo_model": "t"})

    assert analysis["status"] == "succeeded"
    assert {"result.res_bus", "result.res_line", "result.res_ext_grid"} <= _dataset_names(
        grid, str(analysis["result_ref"])
    )


def test_three_phase_powerflow_captures_all_phase_result_tables(grid) -> None:
    analysis = _run(
        grid,
        _open(grid, "ieee_european_lv_asymmetric"),
        "powerflow.three_phase",
        {"max_iteration": "auto", "numba": False},
    )

    datasets = _dataset_names(grid, str(analysis["result_ref"]))
    assert analysis["status"] == "succeeded"
    assert {"result.res_bus_3ph", "result.res_line_3ph", "result.res_asymmetric_load_3ph"} <= datasets


@pytest.mark.parametrize("operation", ["opf.ac", "opf.dc"])
def test_opf_captures_objective_and_network_results(grid, operation: str) -> None:
    analysis = _run(grid, _open(grid, "case14"), operation, {"suppress_warnings": True})

    datasets = _dataset_names(grid, str(analysis["result_ref"]))
    assert analysis["status"] == "succeeded"
    assert {"result.res_objective", "result.res_bus", "result.res_line"} <= datasets


def test_infeasible_opf_is_persisted_as_a_typed_non_converged_outcome(grid) -> None:
    base = _open(grid, "case14")
    infeasible = grid.call(
        "model.revision.derive",
        {
            "context_ref": base,
            "patches": [
                {
                    "operation": "set",
                    "kind": kind,
                    "selector": {"where": {}},
                    "values": {"min_p_mw": 0.0, "max_p_mw": 0.0},
                }
                for kind in ("ext_grid", "gen")
            ],
        },
    )

    analysis = _run(grid, str(infeasible["context_ref"]), "opf.ac", {"suppress_warnings": True})

    assert analysis["status"] == "non_converged"
    assert analysis["summary"]["converged"] is False
    assert "result.res_bus" in _dataset_names(grid, str(analysis["result_ref"]))


@pytest.mark.parametrize(("fault", "case"), [("3ph", "max"), ("2ph", "min"), ("1ph", "max")])
def test_iec60909_supports_fault_cases_selected_buses_and_branch_results(
    grid, fault: str, case: str
) -> None:
    created = grid.call(
        "model.create",
        {
            "name": f"short-circuit-{fault}-{case}",
            "sn_mva": 100.0,
            "f_hz": 50.0,
            "elements": [
                {"id": "bus", "creator": "bus", "arguments": {"vn_kv": 110.0}},
                {
                    "id": "source",
                    "creator": "ext_grid",
                    "arguments": {
                        "bus": {"element_ref": "bus"},
                        "s_sc_max_mva": 5000.0,
                        "s_sc_min_mva": 3000.0,
                        "rx_max": 0.1,
                        "rx_min": 0.1,
                        "x0x_max": 1.0,
                        "r0x0_max": 0.1,
                    },
                },
            ],
        },
    )
    analysis = _run(
        grid,
        str(created["context_ref"]),
        "short_circuit.iec60909",
        {"bus": [0], "fault": fault, "case": case, "branch_results": True},
    )

    assert analysis["status"] == "succeeded"
    assert "result.res_bus_sc" in _dataset_names(grid, str(analysis["result_ref"]))


def _measured_case9_context(grid) -> str:
    context_ref = _open(grid, "case9")
    powerflow = _run(grid, context_ref, "powerflow.ac")
    buses = grid.call(
        "result.dataset.query",
        {
            "result_ref": powerflow["result_ref"],
            "dataset": "result.res_bus",
            "select": ["index", "vm_pu", "p_mw", "q_mvar"],
            "limit": 100,
        },
    )["rows"]
    patches = []
    for row in buses:
        for measurement_type, field, std_dev in (
            ("v", "vm_pu", 0.01),
            ("p", "p_mw", 0.02),
            ("q", "q_mvar", 0.02),
        ):
            patches.append(
                {
                    "operation": "create",
                    "id": f"m-{row['index']}-{measurement_type}",
                    "creator": "measurement",
                    "arguments": {
                        "meas_type": measurement_type,
                        "element_type": "bus",
                        "value": row[field],
                        "std_dev": std_dev,
                        "element": row["index"],
                    },
                }
            )
    derived = grid.call("model.revision.derive", {"context_ref": context_ref, "patches": patches})
    return str(derived["context_ref"])


def test_state_estimation_and_bad_data_workflow_is_published_end_to_end(grid) -> None:
    measured = _measured_case9_context(grid)
    estimated = _run(grid, measured, "state_estimation.estimate", {"algorithm": "wls"})
    chi2 = _run(grid, measured, "state_estimation.chi2", {"chi2_prob_false": 0.05})
    removed = _run(grid, measured, "state_estimation.remove_bad_data", {"rn_max_threshold": 3.0})

    assert estimated["status"] == "succeeded"
    assert estimated["summary"]["success"] is True
    assert {"result.res_bus_est", "result.res_line_est"} <= _dataset_names(
        grid, str(estimated["result_ref"])
    )
    assert chi2["status"] == "succeeded"
    assert isinstance(chi2["summary"]["bad_data_detected"], bool)
    assert removed["status"] == "succeeded"


def test_diagnostic_normalizes_findings_as_a_queryable_result_dataset(grid) -> None:
    analysis = _run(grid, _open(grid, "case9"), "diagnostic.run")
    queried = grid.call(
        "result.dataset.query",
        {
            "result_ref": analysis["result_ref"],
            "dataset": "result.res_diagnostic",
            "select": ["check", "finding_count", "details_json"],
            "limit": 100,
        },
    )

    assert analysis["status"] == "succeeded"
    assert analysis["summary"]["check_count"] == queried["row_count"]
    assert queried["row_count"] >= 1
    assert all(row["check"] for row in queried["rows"])


def test_analysis_failure_preserves_safe_pandapower_diagnostics(grid) -> None:
    error = grid.call_error(
        "analysis.run",
        {
            "context_ref": _open(grid, "case9"),
            "operation": "short_circuit.iec60909",
            "options": {},
        },
    )

    assert error.code == "analysis_failed"
    assert error.phase == "execute"
    assert error.details["operation"] == "short_circuit.iec60909"
    assert error.details["exception_type"] == "ValueError"
    assert "s_sc_max_mva" in error.details["exception_message"]
