from __future__ import annotations

from pathlib import Path
import json

from grid_simulator.operations import dispatch
from grid_simulator.protocol import SimulatorRequest


def request(operation: str, arguments: dict[str, object]) -> SimulatorRequest:
    return SimulatorRequest(protocol_version="1.0", request_id="req-1", operation=operation, arguments=arguments)


def test_registry_is_discoverable(tmp_path: Path) -> None:
    response = dispatch(request("capabilities.list", {}), tmp_path)

    assert response.ok is True
    assert response.result is not None
    ids = {item["id"] for item in response.result["capabilities"]}
    assert {"network.open", "element.resolve", "powerflow.run_ac", "results.lines", "contingency.run_lines"} <= ids


def test_line_index_11_resolves_user_bus_names(tmp_path: Path) -> None:
    opened = dispatch(request("network.open", {"network": "ieee39"}), tmp_path)
    assert opened.result is not None
    resolved = dispatch(
        request(
            "element.resolve",
            {
                "network_ref": opened.result["network_ref"],
                "element": "line",
                "namespace": "index",
                "query": "11",
            },
        ),
        tmp_path,
    )

    assert resolved.ok is True
    assert resolved.result is not None
    assert resolved.result["element_id"] == "line:index:11"
    assert resolved.result["from_bus"]["name"] == "6"
    assert resolved.result["to_bus"]["name"] == "11"


def test_cli_writes_exactly_one_json_response(monkeypatch, capsys, tmp_path: Path) -> None:
    from grid_simulator.cli import main

    monkeypatch.setattr("sys.stdin", _TextInput('{"protocol_version":"1.0","request_id":"cli-1","operation":"capabilities.list","arguments":{}}\n'))

    assert main(["request", "--workspace", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    response = json.loads(output)
    assert response["request_id"] == "cli-1"
    assert response["ok"] is True
    assert output.count("\n") == 1


class _TextInput:
    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        return self.text
