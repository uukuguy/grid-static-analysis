from __future__ import annotations

from pathlib import Path

from grid_simulator.operations import dispatch
from grid_simulator.protocol import SimulatorRequest


def test_network_open_rejects_unknown_network(tmp_path: Path) -> None:
    response = dispatch(
        SimulatorRequest(protocol_version="1.0", request_id="bad-network", operation="network.open", arguments={"network": "other"}),
        tmp_path,
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unsupported_network"
