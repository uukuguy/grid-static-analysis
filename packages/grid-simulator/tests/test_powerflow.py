from __future__ import annotations

from pathlib import Path

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


def test_semantic_powerflow_and_ranking_ids_are_unsupported_until_contract_payloads_exist(tmp_path: Path) -> None:
    powerflow = dispatch(
        _request("analysis.powerflow.ac.run", {"context_ref": "context:sha256:" + "a" * 64}),
        tmp_path,
    )
    ranking = dispatch(
        _request("result.branches.rank", {"result_ref": "result:sha256:" + "b" * 64}),
        tmp_path,
    )

    assert powerflow.ok is False
    assert powerflow.error is not None
    assert powerflow.error.code == "unsupported_capability"
    assert ranking.ok is False
    assert ranking.error is not None
    assert ranking.error.code == "unsupported_capability"
