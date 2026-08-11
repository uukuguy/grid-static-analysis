from __future__ import annotations

from pathlib import Path

import pytest

from grid_simulator.operations import dispatch
from grid_simulator.protocol import SimulatorRequest


def _request(operation: str, arguments: dict[str, object]) -> SimulatorRequest:
    return SimulatorRequest(protocol_version="1.0", request_id=f"req-{operation}", operation=operation, arguments=arguments)


def _result(operation: str, arguments: dict[str, object], workspace: Path) -> dict[str, object]:
    response = dispatch(_request(operation, arguments), workspace)
    assert response.ok, response.error
    assert response.result is not None
    return response.result


def test_ieee39_ac_golden(tmp_path: Path) -> None:
    network_ref = _result("network.open", {"network": "ieee39"}, tmp_path)["network_ref"]
    result = _result("powerflow.run_ac", {"network_ref": network_ref}, tmp_path)

    assert result["converged"] is True
    assert result["total_active_loss_mw"] == pytest.approx(43.64112576084923, abs=1e-8)
    ranked = _result(
        "results.lines",
        {"result_ref": result["result_ref"], "sort": "loading_percent", "limit": 5},
        tmp_path,
    )
    assert [line["index"] for line in ranked["lines"]] == [21, 11, 26, 2, 29]
