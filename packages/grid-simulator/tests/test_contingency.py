from __future__ import annotations

from pathlib import Path

from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest


def _response(capability: str, arguments: dict[str, object], workspace: Path):
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
    return response


def test_semantic_contingency_id_is_unsupported_until_contract_payload_exists(tmp_path: Path) -> None:
    result = _response(
        "analysis.contingency.n_minus_one.run",
        {
            "context_ref": "context:sha256:" + "a" * 64,
            "line_ids": ["line:index:11"],
            "policy": "static-analysis-v1",
        },
        tmp_path,
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unsupported_capability"
