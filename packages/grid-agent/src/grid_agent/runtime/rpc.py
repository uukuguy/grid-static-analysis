from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, Protocol

from grid_agent.observability.trace import JsonlTraceWriter
from grid_agent.runtime.lock import PiCommand
from grid_agent.runtime.environment import PiLaunch


SemanticEventCallback = Callable[[dict[str, Any]], None]
TRACEABLE_RPC_TYPES = frozenset({"prompt_ack", "response", "tool_execution_start", "tool_execution_end", "agent_end"})


class RpcWorkspace(Protocol):
    @property
    def root_path(self) -> Path: ...


class PiProtocolError(RuntimeError):
    pass


class PiRpcClient:
    def __init__(self, command: PiCommand | PiLaunch, workspace: RpcWorkspace, trace: JsonlTraceWriter, *, environment: dict[str, str] | None = None) -> None:
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
        on_semantic_event: SemanticEventCallback | None = None,
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
        pending_tool_calls: list[dict[str, str]] = []
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
            if on_event is not None:
                on_event(event)
            if event.get("type") == "text_delta":
                text.append(str(event.get("text", "")))
            if event.get("type") == "message_update":
                assistant_event = event.get("assistantMessageEvent")
                if isinstance(assistant_event, dict) and assistant_event.get("type") == "text_delta":
                    text.append(str(assistant_event.get("delta", "")))
            for payload in _semantic_trace_payloads(event, "".join(text), pending_tool_calls):
                self.trace.append("pi_event", payload)
                if on_semantic_event is not None:
                    on_semantic_event(payload)
            if event.get("type") == "prompt_ack" and event.get("ok") is True:
                acknowledged = True
            if event.get("type") == "response" and event.get("command") == "prompt":
                if event.get("success") is True:
                    acknowledged = True
                else:
                    raise PiProtocolError(f"Pi prompt failed: {event.get('error', 'unknown error')}")
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
    return event.get("type") not in TRACEABLE_RPC_TYPES


def _semantic_trace_payloads(event: dict[str, Any], assembled_public_text: str, pending_tool_calls: list[dict[str, str]]) -> tuple[dict[str, Any], ...]:
    canonical_tool_result = _canonical_tool_result_event(event, pending_tool_calls)
    if canonical_tool_result is not None:
        return (canonical_tool_result,)
    if _skip_trace_event(event):
        return ()
    event_type = event.get("type")
    if event_type in {"prompt_ack", "response"}:
        return (_acknowledgement_event(event),)
    if event_type == "tool_execution_start":
        start = _canonical_tool_start_event(event)
        pending = {
            key: value
            for key, value in {
                "tool_call_id": start.get("tool_call_id"),
                "tool_name": start.get("tool_name"),
            }.items()
            if isinstance(value, str)
        }
        if pending:
            pending_tool_calls.append(pending)
        return (start,)
    if event_type == "agent_end":
        payloads = [_canonical_agent_end_event(event, assembled_public_text)]
        if assembled_public_text.strip():
            payloads.append({"type": "assistant_message", "text": assembled_public_text})
        return tuple(payloads)
    return ()


def _acknowledgement_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event[key]
        for key in ("type", "command", "success", "ok")
        if key in event
    }


def _canonical_tool_start_event(event: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "tool_execution_start"}
    tool_call_id = _event_tool_call_id(event)
    tool_name = _event_tool_name(event)
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    if tool_name is not None:
        payload["tool_name"] = tool_name
        payload["toolName"] = tool_name
    args = event.get("args")
    if isinstance(args, dict):
        payload["args"] = args
    return payload


def _canonical_agent_end_event(event: dict[str, Any], assembled_public_text: str) -> dict[str, Any]:
    if _provider_error(event):
        stop_status = "error"
    elif assembled_public_text.strip():
        stop_status = "answered"
    else:
        stop_status = "no_answer"
    return {"type": "agent_end", "stop_status": stop_status}


def _canonical_tool_result_event(event: dict[str, Any], pending_tool_calls: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    if event.get("type") not in {"tool_execution_end", "tool_result"}:
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
        "type": "tool_result",
        "event": "tool_result",
        "capability": capability,
        "ok": ok,
        "result": result,
        "evidence_refs": [reference for reference in evidence_refs if isinstance(reference, str)],
    }
    tool_pair = _consume_tool_pair(event, pending_tool_calls)
    tool_call_id = tool_pair.get("tool_call_id")
    tool_name = tool_pair.get("tool_name")
    if isinstance(tool_call_id, str):
        canonical["tool_call_id"] = tool_call_id
    if isinstance(tool_name, str):
        canonical["tool_name"] = tool_name
        canonical["toolName"] = tool_name
    if error is not None:
        canonical["error"] = error
    return canonical


def _tool_result_details(event: dict[str, Any]) -> object:
    if event.get("type") == "tool_result":
        return event
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


def _consume_tool_pair(event: dict[str, Any], pending_tool_calls: list[dict[str, str]] | None) -> dict[str, str]:
    event_pair = {
        key: value
        for key, value in {
            "tool_call_id": _event_tool_call_id(event),
            "tool_name": _event_tool_name(event),
        }.items()
        if isinstance(value, str)
    }
    if pending_tool_calls is None:
        return event_pair
    pending_index = _matching_pending_tool_index(pending_tool_calls, event_pair)
    pending_pair = pending_tool_calls.pop(pending_index) if pending_index is not None else {}
    return {**pending_pair, **event_pair}


def _matching_pending_tool_index(pending_tool_calls: list[dict[str, str]], event_pair: dict[str, str]) -> int | None:
    tool_call_id = event_pair.get("tool_call_id")
    if tool_call_id is not None:
        for index, pending in enumerate(pending_tool_calls):
            if pending.get("tool_call_id") == tool_call_id:
                return index
    tool_name = event_pair.get("tool_name")
    if tool_name is not None:
        for index, pending in enumerate(pending_tool_calls):
            if pending.get("tool_name") == tool_name:
                return index
    if pending_tool_calls:
        return 0
    return None


def _event_tool_call_id(event: dict[str, Any]) -> str | None:
    return _string_value(event, "toolCallId") or _string_value(event, "tool_call_id")


def _event_tool_name(event: dict[str, Any]) -> str | None:
    return _string_value(event, "toolName") or _string_value(event, "tool_name")


def _string_value(event: dict[str, Any], key: str) -> str | None:
    value = event.get(key)
    return value if isinstance(value, str) and value else None
