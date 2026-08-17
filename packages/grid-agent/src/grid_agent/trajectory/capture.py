"""Deterministic mapping from Pi runtime observations to native run events."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from grid_agent.analysis.integrity import ContentReferenceVerifier
from grid_agent.trajectory.artifacts import ArtifactPointer, ImmutableArtifactRegistry
from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import (
    Causation,
    EventDraft,
    EventRefs,
    EventSource,
    EventType,
    RunScope,
)
from grid_agent.trajectory.recorder import RunEventRecorder
from grid_agent.trajectory.request_input import (
    CanonicalModelRequestDocument,
    CanonicalRequestValidationError,
    validate_canonical_model_request_document,
)


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
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_PUBLIC_OPTION_KEYS = frozenset(
    {
        "reasoning",
        "thinkingBudgets",
        "temperature",
        "maxTokens",
        "transport",
        "cacheRetention",
        "timeoutMs",
        "websocketConnectTimeoutMs",
        "maxRetries",
        "maxRetryDelayMs",
    }
)
_REASONING_VALUES = frozenset({"minimal", "low", "medium", "high", "xhigh", "max"})
_TRANSPORT_VALUES = frozenset({"sse", "websocket", "websocket-cached", "auto"})
_CACHE_RETENTION_VALUES = frozenset({"none", "short", "long"})
_THINKING_BUDGET_KEYS = frozenset({"minimal", "low", "medium", "high"})
_NUMERIC_OPTION_KEYS = frozenset(
    {
        "temperature",
        "maxTokens",
        "timeoutMs",
        "websocketConnectTimeoutMs",
        "maxRetries",
        "maxRetryDelayMs",
    }
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
        acknowledgements_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.recorder = recorder
        self.artifacts = artifacts
        self.workspace = workspace
        self.acknowledgements_path = acknowledgements_path
        self.clock = clock
        self._turn_id: str | None = None
        self._step_ordinal = 0
        self._last_request_index = 0
        self._seen_requests: set[str] = set()
        self._current_request: _RequestState | None = None
        self._requests: list[_RequestState] = []
        self._tool_round_request: _RequestState | None = None
        self._tool_calls: dict[str, _ToolState] = {}
        self._awaiting_tool_round_completion = False
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
        self._requests.clear()
        self._tool_round_request = None
        self._tool_calls.clear()
        self._awaiting_tool_round_completion = False
        self._last_retry_attempt = None
        self._last_retry_max_attempts = None

    def drain_model_requests(self) -> None:
        turn_id = self._require_turn()
        for path in sorted(self.workspace.requests_path.glob("*/input.json")):
            # The directory name is the request identity by contract.  Check
            # it before loading the document so the high-frequency poll never
            # reparses and rehashes the complete historical conversation.
            if path.parent.name in self._seen_requests:
                continue
            document = self._load_request_document(path)
            request_id = document.request_id
            if document.turn_id != turn_id:
                continue
            request_index = document.request_index
            if request_index <= self._last_request_index:
                raise CaptureIntegrityError(
                    "model request indexes must be monotonically increasing"
                )
            if path.parent.name != request_id:
                raise CaptureIntegrityError("model request path does not match request_id")
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
                        "semantic_digest_verified": document.semantic_digest_verified,
                        "semantic_request_sha256": document.semantic_request_sha256,
                        "expected_semantic_request_sha256": document.expected_semantic_request_sha256,
                    },
                    causation=(
                        Causation(parent_sequence=document.source_event_sequences[-1])
                    ),
                    source=self._source(),
                    refs=EventRefs(produced=(pointer.ref,)),
                )
            )
            self._write_commit_acknowledgement(document, pointer, event.sequence)
            request = _RequestState(
                request_id=request_id,
                step_id=step_id,
                request_index=request_index,
                started_at=started_at,
                event_sequence=event.sequence,
                provider=document.provider,
                model=document.model,
            )
            self._current_request = request
            self._requests.append(request)
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
            if provider_error is not None and (
                self._current_request is None
                or any(not request.settled for request in self._requests)
            ):
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
        while any(not request.settled for request in self._requests):
            self._fail_response(
                "interrupted", "turn ended before the provider request settled"
            )
        self._turn_id = None
        self._current_request = None
        self._requests.clear()
        self._tool_round_request = None
        self._tool_calls.clear()
        self._awaiting_tool_round_completion = False
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
        self._awaiting_tool_round_completion = stop_reason == "toolUse"
        if self._awaiting_tool_round_completion:
            self._tool_round_request = request

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
        self._awaiting_tool_round_completion = False
        self._tool_round_request = None

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
        request = self._tool_round_request or self._require_request()
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
        tool_call_id = self._required_string(event, "tool_call_id")
        tool = self._tool_calls.get(tool_call_id)
        if tool is None:
            raise CaptureIntegrityError(
                f"tool_call_id has no matching tool start: {tool_call_id}"
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
        if not self._tool_calls:
            self._awaiting_tool_round_completion = False
            self._tool_round_request = None

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
        request = next(
            (candidate for candidate in self._requests if not candidate.settled),
            None,
        )
        if (
            request is not None
            and not request.settled
            and request.first_token_at is None
            and isinstance(value, str)
            and value
        ):
            request.first_token_at = self.clock()

    def _load_request_document(self, path: Path) -> CanonicalModelRequestDocument:
        try:
            display_path = path.relative_to(self.workspace.root_path).as_posix()
        except ValueError:
            display_path = path.name
        location = f"request_id={path.parent.name} input={display_path}"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureIntegrityError(
                f"model request validation failed ({location}): unreadable JSON"
            ) from exc
        if not isinstance(document, Mapping):
            raise CaptureIntegrityError(
                f"model request validation failed ({location}): request must be a JSON object"
            )
        try:
            return validate_canonical_model_request_document(
                document,
                require_digest_match=False,
            )
        except CanonicalRequestValidationError as exc:
            raise CaptureIntegrityError(
                f"model request validation failed ({location}): {exc}"
            ) from exc

    def _write_commit_acknowledgement(
        self,
        document: CanonicalModelRequestDocument,
        pointer: ArtifactPointer,
        event_sequence: int,
    ) -> None:
        path = (
            self.acknowledgements_path
            or _acknowledgements_path(self.workspace, self.recorder.analysis_id)
        ) / f"{document.request_id}.committed.json"
        _write_json_exclusive_atomic(
            path,
            {
                "schema_version": "grid-model-request-commit/1.0",
                "request_id": document.request_id,
                "semantic_request_sha256": document.semantic_request_sha256,
                "artifact_ref": pointer.ref,
                "event_sequence": event_sequence,
                "status": "committed",
            },
        )

    @staticmethod
    def _validate_runtime(value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("runtime must be an object")
        expected = {
            "pi_coding_agent_version",
            "pi_ai_version",
            "pi_source_commit",
            "pi_patch_set_sha256",
        }
        if set(value) != expected:
            raise CaptureIntegrityError("runtime shape is invalid")
        for key in ("pi_coding_agent_version", "pi_ai_version"):
            item = value.get(key)
            if not isinstance(item, str) or not item:
                raise CaptureIntegrityError(f"runtime {key} must be a non-empty string")
        source_commit = value.get("pi_source_commit")
        if not isinstance(source_commit, str) or not _SOURCE_COMMIT_PATTERN.fullmatch(source_commit):
            raise CaptureIntegrityError("runtime pi_source_commit is invalid")
        patch_hash = value.get("pi_patch_set_sha256")
        if not isinstance(patch_hash, str) or not _SHA256_PATTERN.fullmatch(patch_hash):
            raise CaptureIntegrityError("runtime pi_patch_set_sha256 is invalid")

    def _semantic_request(self, value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request must be an object")
        if set(value) != {"model", "context", "options"}:
            raise CaptureIntegrityError("semantic_request shape is invalid")
        self._semantic_model(value.get("model"))
        self._semantic_context(value.get("context"))
        self._semantic_options(value.get("options"))
        return value

    def _semantic_model(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request.model must be an object")
        if set(value) != {"provider", "api", "id"}:
            raise CaptureIntegrityError("semantic_request.model shape is invalid")
        self._required_string(value, "provider")
        self._required_string(value, "api")
        self._required_string(value, "id")

    def _semantic_context(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request.context must be an object")
        if set(value) != {"system_prompt", "messages", "tools"}:
            raise CaptureIntegrityError("semantic_request.context shape is invalid")
        system_prompt = value.get("system_prompt")
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise CaptureIntegrityError("semantic_request.context.system_prompt is invalid")
        messages = value.get("messages")
        tools = value.get("tools")
        if not isinstance(messages, list):
            raise CaptureIntegrityError("semantic_request.context.messages must be an array")
        if not isinstance(tools, list):
            raise CaptureIntegrityError("semantic_request.context.tools must be an array")
        for message in messages:
            self._semantic_message(message)
        for tool in tools:
            self._semantic_tool(tool)

    def _semantic_message(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request message must be an object")
        role = value.get("role")
        if role == "user":
            if set(value) != {"role", "content"}:
                raise CaptureIntegrityError("semantic_request user message shape is invalid")
            self._semantic_user_content(value.get("content"))
            return
        if role == "assistant":
            if set(value) != {"role", "content"}:
                raise CaptureIntegrityError("semantic_request assistant message shape is invalid")
            content = value.get("content")
            if not isinstance(content, list):
                raise CaptureIntegrityError("assistant.content must be an array")
            for block in content:
                self._semantic_assistant_content_block(block)
            return
        if role == "toolResult":
            if set(value) != {"role", "toolCallId", "toolName", "content", "details", "isError"}:
                raise CaptureIntegrityError("semantic_request tool result message shape is invalid")
            self._required_string(value, "toolCallId")
            self._required_string(value, "toolName")
            self._semantic_user_content(value.get("content"))
            _validate_json_leaf(value.get("details"), "toolResult.details")
            if not isinstance(value.get("isError"), bool):
                raise CaptureIntegrityError("toolResult.isError must be boolean")
            return
        raise CaptureIntegrityError("semantic_request message role is invalid")

    def _semantic_user_content(self, value: object) -> None:
        if not isinstance(value, list):
            raise CaptureIntegrityError("user content must be an array")
        for block in value:
            self._semantic_user_content_block(block)

    def _semantic_user_content_block(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("user content block must be an object")
        block_type = value.get("type")
        if block_type == "text":
            if set(value) != {"type", "text"}:
                raise CaptureIntegrityError("text content shape is invalid")
            text = value.get("text")
            if not isinstance(text, str):
                raise CaptureIntegrityError("text.text must be a string")
            return
        if block_type == "image":
            if set(value) != {"type", "data", "mimeType"}:
                raise CaptureIntegrityError("image content shape is invalid")
            self._required_string(value, "data")
            self._required_string(value, "mimeType")
            return
        raise CaptureIntegrityError("user content block type is invalid")

    def _semantic_assistant_content_block(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("assistant content block must be an object")
        block_type = value.get("type")
        if block_type == "text":
            if set(value) != {"type", "text"}:
                raise CaptureIntegrityError("assistant text content shape is invalid")
            text = value.get("text")
            if not isinstance(text, str):
                raise CaptureIntegrityError("text.text must be a string")
            return
        if block_type == "thinking":
            if set(value) != {"type", "redacted"} or value.get("redacted") is not True:
                raise CaptureIntegrityError("assistant thinking content shape is invalid")
            return
        if block_type == "toolCall":
            if set(value) != {"type", "id", "name", "arguments"}:
                raise CaptureIntegrityError("assistant toolCall content shape is invalid")
            self._required_string(value, "id")
            self._required_string(value, "name")
            arguments = value.get("arguments")
            if not isinstance(arguments, Mapping):
                raise CaptureIntegrityError("toolCall.arguments must be an object")
            _validate_json_leaf(arguments, "toolCall.arguments")
            return
        raise CaptureIntegrityError("assistant content block type is invalid")

    def _semantic_tool(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request tool must be an object")
        if set(value) != {"name", "description", "parameters"}:
            raise CaptureIntegrityError("semantic_request tool shape is invalid")
        self._required_string(value, "name")
        if not isinstance(value.get("description"), str):
            raise CaptureIntegrityError("tool.description must be a string")
        parameters = value.get("parameters")
        if not isinstance(parameters, Mapping):
            raise CaptureIntegrityError("tool.parameters must be an object")
        _validate_json_leaf(parameters, "tool.parameters")

    def _semantic_options(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("semantic_request.options must be an object")
        if set(value) - _PUBLIC_OPTION_KEYS:
            raise CaptureIntegrityError("semantic_request.options has unknown fields")
        for key, item in value.items():
            if key == "reasoning":
                if item not in _REASONING_VALUES:
                    raise CaptureIntegrityError("options.reasoning is invalid")
            elif key == "transport":
                if item not in _TRANSPORT_VALUES:
                    raise CaptureIntegrityError("options.transport is invalid")
            elif key == "cacheRetention":
                if item not in _CACHE_RETENTION_VALUES:
                    raise CaptureIntegrityError("options.cacheRetention is invalid")
            elif key == "thinkingBudgets":
                self._semantic_thinking_budgets(item)
            elif key in _NUMERIC_OPTION_KEYS:
                _nonnegative_number(item, f"options.{key}")

    def _semantic_thinking_budgets(self, value: object) -> None:
        if not isinstance(value, Mapping):
            raise CaptureIntegrityError("options.thinkingBudgets must be an object")
        if set(value) - _THINKING_BUDGET_KEYS:
            raise CaptureIntegrityError("options.thinkingBudgets has unknown fields")
        for key, item in value.items():
            _nonnegative_number(item, f"options.thinkingBudgets.{key}")

    @staticmethod
    def _source_sequences(document: Mapping[str, Any]) -> tuple[int, ...]:
        values = document.get("source_event_sequences")
        if not isinstance(values, list) or not values or any(
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
        self._require_turn()
        request = next(
            (candidate for candidate in self._requests if not candidate.settled),
            None,
        )
        if request is None:
            raise CaptureIntegrityError("capture has no unsettled provider request")
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


def _acknowledgements_path(workspace: CaptureWorkspace, analysis_id: str) -> Path:
    configured = getattr(workspace, "trajectory_acks_path", None)
    if isinstance(configured, Path):
        return configured
    return (
        workspace.root_path.parent.parent
        / ".grid-agent"
        / "trajectory-acks"
        / analysis_id
    )


def _write_json_exclusive_atomic(path: Path, payload: object) -> None:
    encoded = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError(f"short write: expected {len(encoded)} bytes, wrote {written}")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise CaptureIntegrityError("model request acknowledgement is unreadable") from exc
            if existing != encoded:
                raise CaptureIntegrityError(
                    "model request acknowledgement already contains different content"
                )
        _fsync_directory(path.parent)
    except OSError as exc:
        raise CaptureIntegrityError(
            f"model request acknowledgement write failed: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_canonical_sorted(value: object) -> str:
    encoded = json.dumps(
        _sort_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sort_json(value: object) -> object:
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    return value


def _validate_json_leaf(value: object, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise CaptureIntegrityError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_leaf(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CaptureIntegrityError(f"{path} contains a non-string key")
            _validate_json_leaf(item, f"{path}.{key}")
        return
    raise CaptureIntegrityError(f"{path} contains a non-JSON value")


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
        or not math.isfinite(value)
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
