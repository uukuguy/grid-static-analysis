from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any

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

    def prompt_and_wait(
        self,
        question: str,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
        heartbeat_seconds: float = 10.0,
        require_answer_text: bool = True,
    ) -> str:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise PiProtocolError("Pi RPC process is not started")
        self.process.stdin.write((json.dumps({"type": "prompt", "message": question}, separators=(",", ":")) + "\n").encode())
        self.process.stdin.flush()
        lines: Queue[bytes | None] = Queue()
        Thread(target=_read_lines, args=(self.process.stdout, lines), daemon=True).start()
        text: list[str] = []
        acknowledged = False
        while True:
            try:
                raw = lines.get(timeout=heartbeat_seconds)
            except Empty:
                if on_heartbeat is not None:
                    on_heartbeat()
                continue
            if raw is None:
                break
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PiProtocolError("Pi RPC returned invalid JSONL") from exc
            canonical_tool_result = _canonical_tool_result_event(event)
            if canonical_tool_result is not None:
                self.trace.append("pi_event", canonical_tool_result)
            elif not _skip_trace_event(event):
                self.trace.append("pi_event", event)
            if on_event is not None:
                on_event(event)
            if event.get("type") == "prompt_ack" and event.get("ok") is True:
                acknowledged = True
            if event.get("type") == "response" and event.get("command") == "prompt":
                if event.get("success") is True:
                    acknowledged = True
                else:
                    raise PiProtocolError(f"Pi prompt failed: {event.get('error', 'unknown error')}")
            if event.get("type") == "text_delta":
                text.append(str(event.get("text", "")))
            if event.get("type") == "message_update":
                assistant_event = event.get("assistantMessageEvent")
                if isinstance(assistant_event, dict) and assistant_event.get("type") == "text_delta":
                    text.append(str(assistant_event.get("delta", "")))
            if event.get("type") == "agent_end":
                if not acknowledged:
                    raise PiProtocolError("Pi agent ended before prompt acknowledgement")
                answer = "".join(text)
                if not answer.strip():
                    provider_error = _provider_error(event)
                    if provider_error:
                        raise PiProtocolError(f"Pi provider failure: {provider_error}")
                    if not require_answer_text:
                        return ""
                    raise PiProtocolError("Pi agent ended without answer text")
                return answer
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


def _read_lines(stream: Any, lines: Queue[bytes | None]) -> None:
    try:
        for raw in stream:
            lines.put(raw)
    finally:
        lines.put(None)


def _provider_error(event: dict[str, Any]) -> str | None:
    messages = event.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("stopReason") == "error":
            error = message.get("errorMessage")
            if isinstance(error, str) and error:
                return error
    return None


def _skip_trace_event(event: dict[str, Any]) -> bool:
    return event.get("type") == "tool_execution_start"


def _canonical_tool_result_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") != "tool_execution_end":
        return None
    details = _tool_result_details(event)
    if not isinstance(details, dict):
        return None
    capability = details.get("capability")
    if not isinstance(capability, str):
        return None
    ok = details.get("ok")
    if ok is not True and ok is not False:
        ok = event.get("isError") is not True
    result = details.get("result", {})
    error = details.get("error")
    evidence_refs = details.get("evidence_refs", [])
    if not isinstance(result, dict):
        result = {}
    if error is not None and not isinstance(error, dict):
        error = {"message": str(error)}
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    canonical: dict[str, Any] = {
        "event": "tool_result",
        "capability": capability,
        "ok": ok,
        "result": result,
        "evidence_refs": [reference for reference in evidence_refs if isinstance(reference, str)],
    }
    if error is not None:
        canonical["error"] = error
    return canonical


def _tool_result_details(event: dict[str, Any]) -> object:
    result = event.get("result")
    if isinstance(result, dict):
        details = result.get("details")
        if isinstance(details, dict):
            return details
        return result
    details = event.get("details")
    if isinstance(details, dict):
        return details
    return None
