"""Deterministic mapping from Pi runtime observations to native run events."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from grid_agent.analysis.integrity import ContentReferenceVerifier
from grid_agent.trajectory.artifacts import ArtifactPointer, ImmutableArtifactRegistry
from grid_agent.trajectory.events import (
    Causation,
    EventDraft,
    EventRefs,
    EventSource,
    EventType,
    RunScope,
)
from grid_agent.trajectory.recorder import RunEventRecorder


SEMANTIC_EVENT_MAP: Mapping[str, EventType] = {
    "tool_execution_start": "tool.started",
    "tool_result": "tool.completed",
}
_SENSITIVE_FIELD = re.compile(
    r"(?:^|_)(?:access_token|api_key|authorization|chain_of_thought|client_secret|"
    r"credential|credentials|hidden_reasoning|password|reasoning|refresh_token|"
    r"secret|token)(?:$|_)",
    re.IGNORECASE,
)


class CaptureWorkspace(Protocol):
    @property
    def root_path(self) -> Path: ...

    @property
    def requests_path(self) -> Path: ...


class CaptureIntegrityError(RuntimeError):
    """Raised when a runtime observation cannot be mapped without inference."""


@dataclass(slots=True)
class _RequestState:
    request_id: str
    step_id: str
    request_index: int
    started_at: float
    event_sequence: int
    provider: str
    model: str
    first_token_at: float | None = None
    settled: bool = False


@dataclass(frozen=True, slots=True)
class _ToolState:
    tool_call_id: str
    tool_name: str
    request_id: str
    step_id: str
    start_sequence: int
    artifact: ArtifactPointer
    arguments: dict[str, Any]


class NativeCaptureAdapter:
    """Capture one Pi turn without persisting streaming or private reasoning."""

    def __init__(
        self,
        recorder: RunEventRecorder,
        artifacts: ImmutableArtifactRegistry,
        workspace: CaptureWorkspace,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.recorder = recorder
        self.artifacts = artifacts
        self.workspace = workspace
        self.clock = clock
        self._turn_id: str | None = None
        self._step_ordinal = 0
        self._last_request_index = 0
        self._seen_requests: set[str] = set()
        self._current_request: _RequestState | None = None
        self._tool_calls: dict[str, _ToolState] = {}
        self._last_retry_attempt: int | None = None
        self._last_retry_max_attempts: int | None = None

    def begin_turn(self, turn_id: str) -> None:
        if self._turn_id is not None:
            raise CaptureIntegrityError("capture already has an active turn")
        if not isinstance(turn_id, str) or not turn_id:
            raise CaptureIntegrityError("turn_id must be a non-empty string")
        self._turn_id = turn_id
        self._step_ordinal = 0
        self._current_request = None
        self._tool_calls.clear()
        self._last_retry_attempt = None
        self._last_retry_max_attempts = None

    def drain_provider_requests(self) -> None:
        turn_id = self._require_turn()
        for path in sorted(self.workspace.requests_path.glob("*/input.json")):
            document = self._load_request_document(path)
            request_id = self._required_string(document, "request_id")
            if request_id in self._seen_requests:
                continue
            request_turn_id = self._required_string(document, "turn_id")
            if request_turn_id != turn_id:
                continue
            request_index = self._required_positive_int(document, "request_index")
            if request_index <= self._last_request_index:
                raise CaptureIntegrityError(
                    "provider request indexes must be monotonically increasing"
                )
            if path.parent.name != request_id:
                raise CaptureIntegrityError(
                    "provider request path does not match request_id"
                )
            if self._current_request is not None and not self._current_request.settled:
                raise CaptureIntegrityError(
                    "a new provider request was captured before the current request settled"
                )

            source_sequences = self._source_sequences(document)
            provider = self._required_string(document, "provider")
            model = self._required_string(document, "model")
            pointer = self.artifacts.register_existing(
                "request-input", request_id, path
            )
            self._step_ordinal += 1
            step_id = f"{turn_id}-s{self._step_ordinal:03d}"
            started_at = self.clock()
            event = self.recorder.append(
                EventDraft(
                    event_type="model.request.started",
                    scope=RunScope(
                        turn_id=turn_id,
                        step_id=step_id,
                        request_id=request_id,
                    ),
                    payload={
                        "artifact_ref": pointer.ref,
                        "request_index": request_index,
                    },
                    causation=(
                        Causation(parent_sequence=source_sequences[-1])
                        if source_sequences
                        else Causation()
                    ),
                    source=self._source(),
                    refs=EventRefs(produced=(pointer.ref,)),
                )
            )
            self._current_request = _RequestState(
                request_id=request_id,
                step_id=step_id,
                request_index=request_index,
                started_at=started_at,
                event_sequence=event.sequence,
                provider=provider,
                model=model,
            )
            self._last_request_index = request_index
            self._seen_requests.add(request_id)

    def on_raw_event(self, event: Mapping[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "text_delta":
            self._observe_first_token(event.get("text"))
            return
        if event_type == "message_update":
            assistant_event = event.get("assistantMessageEvent")
            if (
                isinstance(assistant_event, Mapping)
                and assistant_event.get("type") == "text_delta"
            ):
                self._observe_first_token(assistant_event.get("delta"))
            return
        if event_type == "message_end":
            message = event.get("message")
            if isinstance(message, Mapping) and message.get("role") == "assistant":
                self._complete_response(event, message)
            return
        if event_type == "response" and event.get("command") == "prompt":
            if event.get("success") is False:
                self._fail_response("prompt_error", _error_message(event, "error"))
            return
        if event_type == "agent_end":
            provider_error = _provider_error(event)
            if provider_error is not None:
                self._fail_response("provider_error", provider_error)
            return
        if event_type == "auto_retry_start":
            self._record_retry_started(event)
            return
        if event_type == "auto_retry_end" and event.get("success") is False:
            self._record_retry_exhausted(event)

    def on_semantic_event(
        self, event: Mapping[str, Any], trace_sequence: int
    ) -> None:
        del trace_sequence  # Compatibility trace identity is not native causation.
        semantic_type = (
            "tool_result" if event.get("event") == "tool_result" else event.get("type")
        )
        if semantic_type == "tool_execution_start":
            self._record_tool_start(event)
        elif semantic_type == "tool_result":
            self._record_tool_completion(event)

    def end_turn(self) -> None:
        self._require_turn()
        if self._current_request is not None and not self._current_request.settled:
            self._fail_response(
                "interrupted", "turn ended before the provider request settled"
            )
        self._turn_id = None
        self._current_request = None
        self._tool_calls.clear()
        self._last_retry_attempt = None
        self._last_retry_max_attempts = None

    def _complete_response(
        self, event: Mapping[str, Any], message: Mapping[str, Any]
    ) -> None:
        request = self._require_unsettled_request()
        completed_at = self.clock()
        public_message = _public_assistant_message(message)
        usage = _public_usage(message.get("usage", event.get("usage")))
        stop_reason = _optional_string(
            message.get("stopReason", message.get("stop_reason", event.get("stopReason")))
        )
        ttft_seconds = (
            None
            if request.first_token_at is None
            else max(0.0, request.first_token_at - request.started_at)
        )
        duration_seconds = max(0.0, completed_at - request.started_at)
        response_document = {
            "schema_version": "grid-model-response/1.0",
            "request_id": request.request_id,
            "provider": request.provider,
            "model": request.model,
            "message": public_message,
            "usage": usage,
            "stop_reason": stop_reason,
            "ttft_seconds": ttft_seconds,
            "duration_seconds": duration_seconds,
        }
        pointer = self.artifacts.write_json(
            "model-response", request.request_id, response_document
        )
        payload: dict[str, object] = {
            "artifact_ref": pointer.ref,
            "stop_reason": stop_reason,
            "ttft_seconds": ttft_seconds,
            "duration_seconds": duration_seconds,
        }
        input_tokens = _usage_tokens(usage, "input", "input_tokens", "inputTokens")
        output_tokens = _usage_tokens(
            usage, "output", "output_tokens", "outputTokens"
        )
        if input_tokens is not None:
            payload["input_tokens"] = input_tokens
        if output_tokens is not None:
            payload["output_tokens"] = output_tokens
        self.recorder.append(
            EventDraft(
                event_type="model.response.completed",
                scope=self._request_scope(request),
                causation=Causation(parent_sequence=request.event_sequence),
                source=self._source(),
                refs=EventRefs(produced=(pointer.ref,)),
                payload=payload,
            )
        )
        request.settled = True

    def _fail_response(self, error_type: str, message: str) -> None:
        request = self._require_unsettled_request()
        self.recorder.append(
            EventDraft(
                event_type="model.response.failed",
                scope=self._request_scope(request),
                causation=Causation(parent_sequence=request.event_sequence),
                source=self._source(),
                payload={"error_type": error_type, "message": message},
            )
        )
        request.settled = True

    def _record_retry_started(self, event: Mapping[str, Any]) -> None:
        request = self._require_request()
        attempt = self._required_positive_int(event, "attempt")
        max_attempts = self._required_positive_int(event, "maxAttempts")
        delay_ms = _nonnegative_number(event.get("delayMs"), "delayMs")
        message = _optional_string(event.get("errorMessage"))
        self.recorder.append(
            EventDraft(
                event_type="model.retry.started",
                scope=self._request_scope(request),
                causation=Causation(parent_sequence=request.event_sequence),
                source=self._source(),
                payload={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "delay_seconds": delay_ms / 1000,
                    "message": message,
                },
            )
        )
        self._last_retry_attempt = attempt
        self._last_retry_max_attempts = max_attempts

    def _record_retry_exhausted(self, event: Mapping[str, Any]) -> None:
        request = self._require_request()
        attempt = _positive_int_or_default(
            event.get("attempt"), self._last_retry_attempt, "attempt"
        )
        max_attempts = _positive_int_or_default(
            event.get("maxAttempts"),
            self._last_retry_max_attempts,
            "maxAttempts",
        )
        message = _optional_string(
            event.get("finalError", event.get("errorMessage"))
        )
        self.recorder.append(
            EventDraft(
                event_type="model.retry.exhausted",
                scope=self._request_scope(request),
                causation=Causation(parent_sequence=request.event_sequence),
                source=self._source(),
                payload={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "delay_seconds": None,
                    "message": message,
                },
            )
        )

    def _record_tool_start(self, event: Mapping[str, Any]) -> None:
        request = self._require_unsettled_request()
        tool_call_id = self._required_string(event, "tool_call_id")
        if tool_call_id in self._tool_calls:
            raise CaptureIntegrityError(f"duplicate tool_call_id: {tool_call_id}")
        tool_name = self._required_string(event, "tool_name")
        args = event.get("args", {})
        if not isinstance(args, Mapping):
            raise CaptureIntegrityError("tool args must be an object")
        arguments = dict(args)
        _reject_unsafe_capture(arguments)
        pointer = self.artifacts.write_json(
            "tool-result",
            f"{self._require_turn()}:{tool_call_id}",
            {
                "schema_version": "grid-tool-invocation/1.0",
                "turn_id": self._require_turn(),
                "request_id": request.request_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )
        started = self.recorder.append(
            EventDraft(
                event_type=SEMANTIC_EVENT_MAP["tool_execution_start"],
                scope=RunScope(
                    turn_id=self._require_turn(),
                    step_id=request.step_id,
                    request_id=request.request_id,
                    tool_call_id=tool_call_id,
                ),
                causation=Causation(parent_sequence=request.event_sequence),
                source=self._source(),
                refs=EventRefs(produced=(pointer.ref,)),
                payload={"capability": tool_name, "artifact_ref": pointer.ref},
            )
        )
        self._tool_calls[tool_call_id] = _ToolState(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            request_id=request.request_id,
            step_id=request.step_id,
            start_sequence=started.sequence,
            artifact=pointer,
            arguments=arguments,
        )

    def _record_tool_completion(self, event: Mapping[str, Any]) -> None:
        request = self._require_request()
        tool_call_id = self._required_string(event, "tool_call_id")
        tool = self._tool_calls.get(tool_call_id)
        if tool is None:
            raise CaptureIntegrityError(
                f"tool_call_id has no matching tool start: {tool_call_id}"
            )
        if tool.request_id != request.request_id:
            raise CaptureIntegrityError(
                f"tool_call_id belongs to a different request: {tool_call_id}"
            )
        capability = self._required_string(event, "capability")
        ok = event.get("ok")
        if not isinstance(ok, bool):
            raise CaptureIntegrityError("tool result ok must be boolean")
        result = event.get("result", {})
        if not isinstance(result, Mapping):
            raise CaptureIntegrityError("tool result must be an object")
        decision = self._validated_decision(tool, capability, ok, result)
        result_refs, evidence_refs = self._admit_tool_references(event, result)
        self.artifacts.verify_reference(tool.artifact.ref)
        completed = self.recorder.append(
            EventDraft(
                event_type=SEMANTIC_EVENT_MAP["tool_result"],
                scope=RunScope(
                    turn_id=self._require_turn(),
                    step_id=tool.step_id,
                    request_id=tool.request_id,
                    tool_call_id=tool_call_id,
                ),
                causation=Causation(parent_sequence=tool.start_sequence),
                source=self._source(),
                refs=EventRefs(
                    consumed=(tool.artifact.ref,),
                    produced=result_refs,
                    evidence=evidence_refs,
                ),
                payload={
                    "capability": capability,
                    "artifact_ref": tool.artifact.ref,
                    "ok": ok,
                },
            )
        )
        if decision is not None:
            payload, references = decision
            self.recorder.append(
                EventDraft(
                    event_type="business.decision.declared",
                    scope=completed.scope,
                    causation=Causation(
                        parent_sequence=completed.sequence,
                        correlation_id=tool_call_id,
                    ),
                    source=EventSource(
                        kind="agent-declared",
                        producer="grid-agent.pi-rpc",
                    ),
                    refs=EventRefs(consumed=references),
                    payload=payload,
                )
            )
        del self._tool_calls[tool_call_id]

    def _validated_decision(
        self,
        tool: _ToolState,
        capability: str,
        ok: bool,
        result: Mapping[str, Any],
    ) -> tuple[dict[str, str], tuple[str, ...]] | None:
        decision_name = "grid_record_decision"
        is_decision_tool = tool.tool_name == decision_name
        if is_decision_tool != (capability == decision_name):
            raise CaptureIntegrityError(
                "decision tool name and capability do not match"
            )
        if not is_decision_tool or not ok:
            return None

        expected_keys = {"intent", "decision", "next_action", "refs"}
        if set(result) != expected_keys:
            raise CaptureIntegrityError(
                "decision result must contain only bounded declaration fields"
            )
        if result != tool.arguments:
            raise CaptureIntegrityError(
                "decision result does not match the declared tool arguments"
            )
        payload: dict[str, str] = {}
        for name in ("intent", "decision", "next_action"):
            value = result.get(name)
            if not isinstance(value, str) or not 1 <= len(value) <= 500:
                raise CaptureIntegrityError(
                    f"decision {name} must contain 1 to 500 characters"
                )
            payload[name] = value
        values = result.get("refs")
        if (
            not isinstance(values, list)
            or len(values) > 20
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise CaptureIntegrityError(
                "decision refs must contain at most 20 non-empty strings"
            )
        references = tuple(dict.fromkeys(values))
        allowed = self._decision_allowed_refs()
        if any(reference not in allowed for reference in references):
            raise CaptureIntegrityError(
                "decision refs must be known in the current run"
            )
        return payload, references

    def _decision_allowed_refs(self) -> frozenset[str]:
        path = (
            self.workspace.root_path
            / "context"
            / "trajectory-allowed-refs.json"
        )
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureIntegrityError(
                "decision allowed refs document is unreadable"
            ) from exc
        refs = document.get("refs") if isinstance(document, Mapping) else None
        if (
            not isinstance(refs, list)
            or any(not isinstance(reference, str) or not reference for reference in refs)
        ):
            raise CaptureIntegrityError(
                "decision allowed refs document is invalid"
            )
        return frozenset(refs)

    def _admit_tool_references(
        self, event: Mapping[str, Any], result: Mapping[str, Any]
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        result_refs = _reference_values(result, "result_ref", "result_refs")
        evidence_refs = _dedupe(
            [
                *_reference_values(result, "evidence_ref", "evidence_refs"),
                *_reference_values(event, "evidence_ref", "evidence_refs"),
            ]
        )
        verifier = ContentReferenceVerifier(self.workspace.root_path)
        for reference in result_refs:
            verified = verifier.verify_result(reference)
            self.artifacts.register_existing("result", reference, verified.path)
        for reference in evidence_refs:
            verified = verifier.verify_evidence(reference)
            self.artifacts.register_existing("evidence", reference, verified.path)
        return tuple(result_refs), tuple(evidence_refs)

    def _observe_first_token(self, value: object) -> None:
        request = self._current_request
        if (
            request is not None
            and not request.settled
            and request.first_token_at is None
            and isinstance(value, str)
            and value
        ):
            request.first_token_at = self.clock()

    def _load_request_document(self, path: Path) -> Mapping[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureIntegrityError(
                f"provider request is not readable JSON: {path}"
            ) from exc
        if not isinstance(document, Mapping):
            raise CaptureIntegrityError("provider request must be a JSON object")
        if document.get("schema_version") != "grid-model-request-input/1.0":
            raise CaptureIntegrityError("provider request schema_version is invalid")
        return document

    @staticmethod
    def _source_sequences(document: Mapping[str, Any]) -> tuple[int, ...]:
        values = document.get("source_event_sequences")
        if not isinstance(values, list) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in values
        ):
            raise CaptureIntegrityError(
                "source_event_sequences must contain positive integers"
            )
        if values != sorted(set(values)):
            raise CaptureIntegrityError(
                "source_event_sequences must be strictly increasing"
            )
        return tuple(values)

    @staticmethod
    def _required_string(document: Mapping[str, Any], key: str) -> str:
        value = document.get(key)
        if not isinstance(value, str) or not value:
            raise CaptureIntegrityError(f"{key} must be a non-empty string")
        return value

    @staticmethod
    def _required_positive_int(document: Mapping[str, Any], key: str) -> int:
        value = document.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise CaptureIntegrityError(f"{key} must be a positive integer")
        return value

    def _require_turn(self) -> str:
        if self._turn_id is None:
            raise CaptureIntegrityError("capture has no active turn")
        return self._turn_id

    def _require_request(self) -> _RequestState:
        self._require_turn()
        if self._current_request is None:
            raise CaptureIntegrityError("capture has no current provider request")
        return self._current_request

    def _require_unsettled_request(self) -> _RequestState:
        request = self._require_request()
        if request.settled:
            raise CaptureIntegrityError("current provider request is already settled")
        return request

    def _request_scope(self, request: _RequestState) -> RunScope:
        return RunScope(
            turn_id=self._require_turn(),
            step_id=request.step_id,
            request_id=request.request_id,
        )

    @staticmethod
    def _source() -> EventSource:
        return EventSource(producer="grid-agent.pi-rpc")


def _public_assistant_message(message: Mapping[str, Any]) -> dict[str, object]:
    content = message.get("content")
    public_content: list[dict[str, str]] = []
    if isinstance(content, Sequence) and not isinstance(
        content, (str, bytes, bytearray)
    ):
        for block in content:
            if not isinstance(block, Mapping) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                public_content.append({"type": "text", "text": text})
    return {"role": "assistant", "content": public_content}


def _public_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str)
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _usage_tokens(usage: Mapping[str, int], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return None


def _provider_error(event: Mapping[str, Any]) -> str | None:
    messages = event.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, Mapping) and message.get("stopReason") == "error":
            value = message.get("errorMessage")
            return value if isinstance(value, str) and value else "provider failure"
    return None


def _error_message(event: Mapping[str, Any], key: str) -> str:
    value = event.get(key)
    return value if isinstance(value, str) and value else "unknown error"


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_number(value: object, name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
    ):
        raise CaptureIntegrityError(f"{name} must be a nonnegative number")
    return float(value)


def _positive_int_or_default(
    value: object, default: int | None, name: str
) -> int:
    if value is None:
        if default is None:
            raise CaptureIntegrityError(f"{name} must be a positive integer")
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CaptureIntegrityError(f"{name} must be a positive integer")
    return value


def _reference_values(
    value: Mapping[str, Any], singular: str, plural: str
) -> list[str]:
    references: list[str] = []
    singular_value = value.get(singular)
    if singular_value is not None:
        if not isinstance(singular_value, str):
            raise CaptureIntegrityError(f"{singular} must be a string")
        references.append(singular_value)
    plural_value = value.get(plural)
    if plural_value is not None:
        if not isinstance(plural_value, list) or any(
            not isinstance(item, str) for item in plural_value
        ):
            raise CaptureIntegrityError(f"{plural} must contain strings")
        references.extend(plural_value)
    return _dedupe(references)


def _dedupe(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _reject_unsafe_capture(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _SENSITIVE_FIELD.search(key):
                raise CaptureIntegrityError(
                    "tool arguments contain prohibited credential or reasoning fields"
                )
            _reject_unsafe_capture(item)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            _reject_unsafe_capture(item)
