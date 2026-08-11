from __future__ import annotations

import json
import subprocess
from pathlib import Path

from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter
from grid_agent.runtime.lock import PiCommand
from grid_agent.runtime.environment import PiLaunch


class PiProtocolError(RuntimeError):
    pass


class PiRpcClient:
    def __init__(self, command: PiCommand | PiLaunch, workspace: RunWorkspace, trace: JsonlTraceWriter, *, environment: dict[str, str] | None = None) -> None:
        self.command = command
        self.workspace = workspace
        self.trace = trace
        self.environment = environment
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        launch_environment = self.command.environment if isinstance(self.command, PiLaunch) else self.environment
        self.process = subprocess.Popen(list(self.command.argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.workspace.root_path, env=launch_environment)

    def prompt_and_wait(self, question: str) -> str:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise PiProtocolError("Pi RPC process is not started")
        self.process.stdin.write((json.dumps({"type": "prompt", "text": question}, separators=(",", ":")) + "\n").encode())
        self.process.stdin.flush()
        text: list[str] = []
        acknowledged = False
        for raw in self.process.stdout:
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PiProtocolError("Pi RPC returned invalid JSONL") from exc
            self.trace.append("pi_event", event)
            if event.get("type") == "prompt_ack" and event.get("ok") is True:
                acknowledged = True
            if event.get("type") == "text_delta":
                text.append(str(event.get("text", "")))
            if event.get("type") == "agent_end":
                if not acknowledged:
                    raise PiProtocolError("Pi agent ended before prompt acknowledgement")
                return "".join(text)
        raise PiProtocolError("Pi RPC ended before agent completion")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process = None
