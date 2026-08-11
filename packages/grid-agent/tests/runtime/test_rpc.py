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


def test_rpc_reports_events_and_idle_heartbeats(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json,time\n"
        "json.loads(input())\n"
        "print(json.dumps({'type':'prompt_ack','ok':True}), flush=True)\n"
        "time.sleep(0.03)\n"
        "print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        "print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))
    observed: list[str] = []
    heartbeats: list[None] = []

    client.start()
    try:
        assert client.prompt_and_wait(
            "question",
            on_event=lambda event: observed.append(event["type"]),
            on_heartbeat=lambda: heartbeats.append(None),
            heartbeat_seconds=0.01,
        ) == "answer"
    finally:
        client.stop()

    assert observed == ["prompt_ack", "text_delta", "agent_end"]
    assert heartbeats


def test_rpc_uses_current_pi_prompt_message_protocol(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\n"
        "request=json.loads(input())\n"
        "if request.get('message') != 'question':\n"
        " print(json.dumps({'type':'response','command':'prompt','success':False,'error':'missing message'}), flush=True)\n"
        "else:\n"
        " print(json.dumps({'type':'response','command':'prompt','success':True}), flush=True)\n"
        " print(json.dumps({'type':'text_delta','text':'answer'}), flush=True)\n"
        " print(json.dumps({'type':'agent_end'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        assert client.prompt_and_wait("question") == "answer"
    finally:
        client.stop()


def test_rpc_stops_immediately_on_failed_prompt_response(tmp_path: Path) -> None:
    fake = tmp_path / "fake_pi.py"
    fake.write_text(
        "import json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':False,'error':'preflight failed'}), flush=True)\n",
        encoding="utf-8",
    )
    command = PiCommand(
        argv=(sys.executable, str(fake)),
        identity=PiRuntimeIdentity(path=fake, source="explicit_override", package_version="0.80.6", lock_sha256="lock"),
    )
    workspace = RunWorkspace.create(tmp_path / "runs")
    client = PiRpcClient(command, workspace, JsonlTraceWriter(workspace.events_path))

    client.start()
    try:
        with pytest.raises(PiProtocolError, match="preflight failed"):
            client.prompt_and_wait("question")
    finally:
        client.stop()
