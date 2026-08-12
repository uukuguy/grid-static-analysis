from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from grid_agent.simulator.client import GridctlClient, SimulatorCapabilityError


def test_client_uses_json_stdin_and_clean_stdout(tmp_path: Path) -> None:
    executable = tmp_path / "gridctl"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nrequest=json.loads(sys.stdin.read())\nassert request['capability'] == 'environment.describe'\nprint(json.dumps({'protocol':'grid-capability','protocol_version':'1.0','request_id':request['request_id'],'ok':True,'result':{'executable_capabilities':[{'id':'context.open'}]}},separators=(',',':')))\nprint('diagnostic', file=sys.stderr)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    client = GridctlClient(executable=executable, workspace=tmp_path, timeout_seconds=5)

    result = client.invoke("environment.describe", {})

    assert result["executable_capabilities"]


def test_client_invokes_named_capability(tmp_path: Path) -> None:
    executable = tmp_path / "gridctl"
    request_path = tmp_path / "last-request.json"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"request_path = pathlib.Path({str(request_path)!r})\n"
        "request=json.loads(sys.stdin.read())\n"
        "request_path.write_text(json.dumps(request,sort_keys=True), encoding='utf-8')\n"
        "print(json.dumps({'protocol':'grid-capability','protocol_version':'1.0','request_id':request['request_id'],'ok':True,'result':{'models':[{'model_id':'ieee39'}]}},separators=(',',':')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = GridctlClient(executable=executable, workspace=tmp_path).invoke("model.list", {})

    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert result["models"][0]["model_id"] == "ieee39"
    assert request["protocol"] == "grid-capability"
    assert request["protocol_version"] == "1.0"
    assert request["capability"] == "model.list"
    assert "operation" not in request


def test_client_preserves_typed_capability_error(tmp_path: Path) -> None:
    executable = tmp_path / "gridctl"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "request=json.loads(sys.stdin.read())\n"
        "print(json.dumps({'protocol':'grid-capability','protocol_version':'1.0','request_id':request['request_id'],'ok':False,'error':{'code':'invalid_arguments','phase':'validate','message':'bad input','retryable':False,'state_effect':'none','allowed_recovery_actions':['correct_arguments'],'evidence_refs':['evidence:sha256:'+'1'*64],'details':{'field':'context_ref'}}},separators=(',',':')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    client = GridctlClient(executable=executable, workspace=tmp_path)

    with pytest.raises(SimulatorCapabilityError) as raised:
        client.invoke("context.open", {"unexpected": True})

    assert raised.value.error == {
        "code": "invalid_arguments",
        "phase": "validate",
        "message": "bad input",
        "retryable": False,
        "state_effect": "none",
        "allowed_recovery_actions": ["correct_arguments"],
        "evidence_refs": ["evidence:sha256:" + "1" * 64],
        "details": {"field": "context_ref"},
    }


def test_agent_source_never_imports_pandapower() -> None:
    for path in Path("packages/grid-agent/src").rglob("*.py"):
        assert "import pandapower" not in path.read_text(encoding="utf-8")
