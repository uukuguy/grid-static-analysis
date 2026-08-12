from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest


def _result(capability: str, arguments: dict[str, object], workspace: Path) -> dict[str, object]:
    response = dispatch(
        GridCapabilityRequest(
            protocol="grid-capability",
            protocol_version="1.0",
            request_id="contingency",
            capability=capability,
            arguments=arguments,
        ),
        workspace,
    )
    assert response.ok, response.error
    assert response.result is not None
    return response.result


def test_line_11_outage_has_full_receipt(tmp_path: Path) -> None:
    context_ref = _result("context.open", {"model": "ieee39"}, tmp_path)["context_ref"]
    result = _result(
        "analysis.contingency.n_minus_one.run",
        {"context_ref": context_ref, "line_ids": ["line:index:11"], "policy": "static-analysis-v1"},
        tmp_path,
    )

    scenario = result["scenarios"][0]
    assert scenario["converged"] is True
    assert scenario["max_line_loading_percent"] == pytest.approx(105.97543088358476, abs=1e-8)
    assert [item["index"] for item in scenario["overloaded_lines"]] == [7, 16, 17]
    assert scenario["evidence_id"]
