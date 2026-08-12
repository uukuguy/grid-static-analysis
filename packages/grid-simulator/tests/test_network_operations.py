from __future__ import annotations

from pathlib import Path

from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest


def test_network_open_rejects_unknown_network_argument_at_operation_boundary(tmp_path: Path) -> None:
    response = dispatch(
        GridCapabilityRequest(
            protocol="grid-capability",
            protocol_version="1.0",
            request_id="bad-network",
            capability="context.open",
            arguments={"model": "other"},
        ),
        tmp_path,
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "model_not_found"
    assert response.error.phase == "resolve"
    assert response.error.allowed_recovery_actions == ("call_model_list",)
