from __future__ import annotations

import os
from pathlib import Path

from grid_agent.simulator.client import GridctlClient


def test_client_uses_json_stdin_and_clean_stdout(tmp_path: Path) -> None:
    executable = tmp_path / "gridctl"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nrequest=json.loads(sys.stdin.read())\nprint(json.dumps({'protocol_version':'1.0','request_id':request['request_id'],'ok':True,'result':{'capabilities':[{'id':'network.open'}]}},separators=(',',':')))\nprint('diagnostic', file=sys.stderr)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    client = GridctlClient(executable=executable, workspace=tmp_path, timeout_seconds=5)

    result = client.call("capabilities.list", {})

    assert result["capabilities"]


def test_agent_source_never_imports_pandapower() -> None:
    for path in Path("packages/grid-agent/src").rglob("*.py"):
        assert "import pandapower" not in path.read_text(encoding="utf-8")
