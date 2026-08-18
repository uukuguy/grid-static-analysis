from __future__ import annotations


def test_analysis_operation_catalog_describes_closed_powerflow_schema(grid) -> None:
    listed = grid.call("analysis.operation.list", {})
    by_id = {item["id"]: item for item in listed["operations"]}
    assert by_id["powerflow.ac"]["pandapower_operation"] == "runpp"

    described = grid.call("analysis.operation.describe", {"operation": "powerflow.ac"})
    assert described["operation"] == "powerflow.ac"
    assert described["options_schema"]["additionalProperties"] is False
    assert described["options_schema"]["properties"]["algorithm"]["enum"] == [
        "nr", "iwamoto_nr", "bfsw", "gs", "fdbx", "fdxb"
    ]


def test_analysis_run_rejects_unknown_operation_options_before_execution(grid, context_ref: str) -> None:
    error = grid.call_error(
        "analysis.run",
        {"context_ref": context_ref, "operation": "powerflow.ac", "options": {"python": "open('/tmp/x')"}},
    )

    assert error.code == "analysis_options_invalid"
    assert error.phase == "validate"
    assert grid.engine.ac_run_count == 0


def test_analysis_run_is_idempotent_and_request_identity_is_not_in_result(grid, context_ref: str) -> None:
    first = grid.call("analysis.run", {"context_ref": context_ref, "operation": "powerflow.ac", "options": {}})
    second = grid.call("analysis.run", {"context_ref": context_ref, "operation": "powerflow.ac", "options": {}})

    assert first["result_ref"] == second["result_ref"]
    assert first["operation"] == "powerflow.ac"
    assert first["status"] == "succeeded"
    assert first["datasets"]
    assert grid.engine.ac_run_count == 2


def test_analysis_run_rejects_unknown_operation_without_creating_result(grid, context_ref: str) -> None:
    error = grid.call_error(
        "analysis.run",
        {"context_ref": context_ref, "operation": "python.eval", "options": {}},
    )

    assert error.code == "unknown_analysis_operation"
    assert list(grid.workspace.results_dir.glob("result-*.json")) == []
