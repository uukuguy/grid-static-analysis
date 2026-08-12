from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from grid_simulator.capabilities import CapabilityRegistry
from grid_simulator.operations import dispatch
from grid_simulator.protocol import GridCapabilityRequest, GridCapabilityResponse


def request(capability: str, arguments: dict[str, object]) -> GridCapabilityRequest:
    return GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id="req-1",
        capability=capability,
        arguments=arguments,
    )


def test_request_uses_named_grid_capability_protocol() -> None:
    parsed = GridCapabilityRequest(
        protocol="grid-capability",
        protocol_version="1.0",
        request_id="req-1",
        capability="topology.branch.endpoints.get",
        arguments={
            "context_ref": "context:sha256:" + "a" * 64,
            "branch_ref": "asset:line:sha256:" + "b" * 64,
        },
    )

    assert parsed.capability == "topology.branch.endpoints.get"


def test_request_rejects_legacy_operation_envelope() -> None:
    with pytest.raises(ValidationError):
        GridCapabilityRequest.model_validate(
            {"protocol_version": "1.0", "request_id": "req-1", "operation": "network.open", "arguments": {}}
        )


def test_response_requires_exactly_one_result_or_error() -> None:
    with pytest.raises(ValidationError):
        GridCapabilityResponse(request_id="req-1", ok=True, result=None, error=None)

    with pytest.raises(ValidationError):
        GridCapabilityResponse(request_id="req-1", ok=False, result={"value": 1}, error=None)


def test_contracts_express_composition_and_pandapower_binding() -> None:
    contract = CapabilityRegistry.load_packaged().require("topology.branch.endpoints.get")

    assert contract.tool_name == "grid_topology_branch_endpoints"
    assert "network.branch" in contract.consumes
    assert "topology.endpoints" in contract.produces
    assert contract.pandapower is not None
    assert contract.pandapower.version == "3.4.0"
    assert contract.terms["zh"]
    assert contract.not_for


def test_registry_is_discoverable(tmp_path: Path) -> None:
    response = dispatch(request("environment.describe", {}), tmp_path)

    assert response.ok is True
    assert response.result is not None
    ids = {item["id"] for item in response.result["executable_capabilities"]}
    assert ids == {"environment.describe", "model.list", "context.open", "context.get"}
    assert "capabilities" not in response.result


def test_context_open_rejects_unexpected_arguments_before_persistence(tmp_path: Path) -> None:
    response = dispatch(request("context.open", {"model": "ieee39", "unexpected": True}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_arguments"
    assert response.error.phase == "validate"
    assert response.error.retryable is False
    assert response.error.state_effect == "none"
    assert response.error.allowed_recovery_actions == ("correct_arguments",)
    assert response.error.details == {}
    assert not (tmp_path / "evidence").exists()


def test_model_list_rejects_forbidden_family_argument(tmp_path: Path) -> None:
    response = dispatch(request("model.list", {"family": "other"}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_arguments"
    assert response.error.phase == "validate"
    assert response.error.retryable is False
    assert response.error.state_effect == "none"
    assert response.error.allowed_recovery_actions == ("correct_arguments",)


def test_context_open_valid_arguments_pass_schema_gate(tmp_path: Path) -> None:
    response = dispatch(request("context.open", {"model": "ieee39"}), tmp_path)

    assert response.ok is True
    assert response.result is not None
    assert response.result["context_ref"].startswith("context:sha256:")


def test_unsupported_semantic_id_is_not_reported_as_invalid_arguments(tmp_path: Path) -> None:
    response = dispatch(request("analysis.powerflow.ac.run", {"unexpected": True}), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unsupported_capability"


@pytest.mark.parametrize(
    "capability,arguments",
    (
        ("analysis.powerflow.ac.run", {"context_ref": "context:sha256:" + "a" * 64}),
        ("result.branches.rank", {"result_ref": "result:sha256:" + "b" * 64}),
        (
            "analysis.contingency.n_minus_one.run",
            {
                "context_ref": "context:sha256:" + "a" * 64,
                "line_ids": ["line:index:11"],
                "policy": "static-analysis-v1",
            },
        ),
    ),
)
def test_non_conformant_semantic_analysis_ids_are_unsupported(
    capability: str, arguments: dict[str, object], tmp_path: Path
) -> None:
    response = dispatch(request(capability, arguments), tmp_path)

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "unsupported_capability"


def test_model_element_get_is_unsupported_until_contract_payload_exists(tmp_path: Path) -> None:
    opened = dispatch(request("context.open", {"model": "ieee39"}), tmp_path)
    assert opened.result is not None
    resolved = dispatch(
        request(
            "model.element.get",
            {
                "context_ref": opened.result["context_ref"],
                "element": "line",
                "namespace": "pandapower_index",
                "query": "11",
            },
        ),
        tmp_path,
    )

    assert resolved.ok is False
    assert resolved.error is not None
    assert resolved.error.code == "unsupported_capability"


def test_cli_writes_exactly_one_json_response(monkeypatch, capsys, tmp_path: Path) -> None:
    from grid_simulator.cli import main

    monkeypatch.setattr(
        "sys.stdin",
        _TextInput(
            '{"protocol":"grid-capability","protocol_version":"1.0","request_id":"cli-1",'
            '"capability":"environment.describe","arguments":{}}\n'
        ),
    )

    assert main(["request", "--workspace", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    response = json.loads(output)
    assert response["protocol"] == "grid-capability"
    assert response["request_id"] == "cli-1"
    assert response["ok"] is True
    assert output.count("\n") == 1


class _TextInput:
    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        return self.text
