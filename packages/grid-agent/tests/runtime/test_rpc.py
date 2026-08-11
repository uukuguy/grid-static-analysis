from __future__ import annotations

import sys
from pathlib import Path

import pytest

from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter
from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity
from grid_agent.runtime.rpc import PiProtocolError, PiRpcClient
from grid_agent.runtime.environment import PiLaunch


def test_rpc_requires_ack_before_agent_end(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text("import json; print(json.dumps({'type':'agent_end'}), flush=True)", encoding="utf-8")
    command = PiCommand(argv=(sys.executable, str(fake)), identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"))
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    with pytest.raises(PiProtocolError, match="before prompt acknowledgement"):
        client.prompt_and_wait("question")
    client.stop()


def test_rpc_starts_full_launch_with_its_restricted_environment(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text("import os; assert os.environ['ONLY_ALLOWED'] == 'yes'", encoding="utf-8")
    launch = PiLaunch(argv=(sys.executable, str(fake)), environment={"ONLY_ALLOWED": "yes"})
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(launch, workspace, JsonlTraceWriter(workspace.events_path))
    client.start()
    client.stop()
