from __future__ import annotations

import json
from pathlib import Path

import pytest


GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "ieee39-pandapower-3.4.0.json").read_text(encoding="utf-8")
)["ieee39"]


def _result_document_path(result_ref: str, root: Path) -> Path:
    return root / "evidence" / "results" / f"powerflow-{result_ref.removeprefix('result:sha256:')}.json"


def test_ac_powerflow_records_effective_solver_and_evidence(grid, context_ref: str) -> None:
    result = grid.call("analysis.powerflow.ac.run", {"context_ref": context_ref})

    assert result["converged"] is True
    assert result["solver"]["profile"] == "ac-default-v1"
    assert result["solver"]["algorithm"] == "nr"
    assert result["total_active_loss"]["unit"] == "MW"
    assert result["result_ref"].startswith("result:sha256:")
    assert result["evidence_refs"]


def test_ac_powerflow_persists_complete_normalized_result(grid, context_ref: str) -> None:
    result = grid.call("analysis.powerflow.ac.run", {"context_ref": context_ref})
    document = json.loads(_result_document_path(str(result["result_ref"]), grid.workspace.root).read_text(encoding="utf-8"))

    assert document["result_ref"] == result["result_ref"]
    assert document["context_ref"] == context_ref
    assert document["solver"]["profile"] == "ac-default-v1"
    assert document["convergence"]["converged"] is True
    assert document["losses"]["total_active_loss"]["value"] == pytest.approx(GOLDEN["total_active_loss_mw"])
    assert document["bus_results"]
    assert document["branch_results"]
    assert document["transformer_results"]
    assert document["generator_results"]
    assert document["load_results"]
    assert document["external_grid_results"]
    assert document["branch_results"][0]["asset_ref"].startswith("asset:line:sha256:")
    assert {"loading_percent", "p_from_mw", "p_to_mw", "pl_mw"} <= set(document["branch_results"][0])


def test_branch_ranking_reads_persisted_result_without_rerunning_ac(grid, context_ref: str) -> None:
    powerflow = grid.call("analysis.powerflow.ac.run", {"context_ref": context_ref})
    assert grid.engine.ac_run_count == 1

    ranking = grid.call(
        "result.branches.rank",
        {
            "result_ref": powerflow["result_ref"],
            "metric": "loading_percent",
            "direction": "descending",
            "limit": 5,
            "element_kind": "line",
        },
    )

    assert grid.engine.ac_run_count == 1
    assert ranking["result_ref"] == powerflow["result_ref"]
    assert ranking["metric"] == "loading_percent"
    assert ranking["metric_unit"] == "percent"
    assert [item["pandapower_index"] for item in ranking["branches"]] == GOLDEN["top5_line_indices"]
    assert all(item["branch_ref"].startswith("asset:line:sha256:") for item in ranking["branches"])
