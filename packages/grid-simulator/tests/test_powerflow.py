from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest


def _request(capability: str, arguments: dict[str, object]) -> GridCapabilityRequest:
    return GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id=f"req-{capability}",
        capability=capability,
        arguments=arguments,
    )


def _result(capability: str, arguments: dict[str, object], workspace: Path) -> dict[str, object]:
    response = dispatch(_request(capability, arguments), workspace)
    assert response.ok, response.error
    assert response.result is not None
    return response.result


def test_ieee39_ac_golden(tmp_path: Path) -> None:
    context_ref = _result("context.open", {"model": "ieee39"}, tmp_path)["context_ref"]
    result = _result("analysis.powerflow.ac.run", {"context_ref": context_ref}, tmp_path)

    assert result["converged"] is True
    assert result["total_active_loss_mw"] == pytest.approx(43.64112576084923, abs=1e-8)
    ranked = _result(
        "result.branches.rank",
        {"result_ref": result["result_ref"], "metric": "loading_percent", "limit": 5},
        tmp_path,
    )
    assert [line["index"] for line in ranked["branches"]] == [21, 11, 26, 2, 29]
