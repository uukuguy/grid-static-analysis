"""Validation for canonical v2 model request input artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


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


class CanonicalRequestValidationError(ValueError):
    """Raised when a v2 request artifact is not safe canonical request input."""


@dataclass(frozen=True, slots=True)
class CanonicalModelRequestDocument:
    request_id: str
    turn_id: str
    request_index: int
    source_event_sequences: tuple[int, ...]
    provider: str
    model: str
    semantic_request_sha256: str


def validate_canonical_model_request_document(
    document: Mapping[str, Any],
) -> CanonicalModelRequestDocument:
    if document.get("schema_version") != "grid-model-request-input/2.0":
        raise CanonicalRequestValidationError("model request schema_version is invalid")
    expected_keys = {
        "schema_version",
        "request_id",
        "request_index",
        "turn_id",
        "captured_at",
        "source_event_sequences",
        "context_revision",
        "context_state_hash",
        "runtime",
        "semantic_request",
        "semantic_request_sha256",
    }
    if set(document) != expected_keys:
        raise CanonicalRequestValidationError("model request has unexpected fields")
    captured_at = document.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at:
        raise CanonicalRequestValidationError("captured_at must be a non-empty string")
    context_revision = document.get("context_revision")
    if (
        not isinstance(context_revision, int)
        or isinstance(context_revision, bool)
        or context_revision < 0
    ):
        raise CanonicalRequestValidationError(
            "context_revision must be a nonnegative integer"
        )
    context_hash = document.get("context_state_hash")
    if not isinstance(context_hash, str) or not _SHA256_PATTERN.fullmatch(context_hash):
        raise CanonicalRequestValidationError(
            "context_state_hash must be a sha256 digest"
        )
    _validate_runtime(document.get("runtime"))
    semantic_request = _semantic_request(document.get("semantic_request"))
    supplied_digest = document.get("semantic_request_sha256")
    if not isinstance(supplied_digest, str) or not _SHA256_PATTERN.fullmatch(
        supplied_digest
    ):
        raise CanonicalRequestValidationError(
            "semantic_request_sha256 must be a sha256 digest"
        )
    expected_digest = semantic_request_sha256(semantic_request)
    if supplied_digest != expected_digest:
        raise CanonicalRequestValidationError(
            "semantic_request_sha256 does not match semantic_request"
        )
    model = semantic_request["model"]
    return CanonicalModelRequestDocument(
        request_id=_required_string(document, "request_id"),
        turn_id=_required_string(document, "turn_id"),
        request_index=_required_positive_int(document, "request_index"),
        source_event_sequences=_source_sequences(document),
        provider=_required_string(model, "provider"),
        model=_required_string(model, "id"),
        semantic_request_sha256=supplied_digest,
    )


def canonical_request_preview(document: Mapping[str, Any]) -> dict[str, Any]:
    validate_canonical_model_request_document(document)
    preview_keys = (
        "request_id",
        "request_index",
        "turn_id",
        "captured_at",
        "source_event_sequences",
        "context_revision",
        "context_state_hash",
        "runtime",
        "semantic_request",
        "semantic_request_sha256",
    )
    return {key: document[key] for key in preview_keys}


def semantic_request_sha256(value: object) -> str:
    encoded = json.dumps(
        _sort_json(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_runtime(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError("runtime must be an object")
    expected = {
        "pi_coding_agent_version",
        "pi_ai_version",
        "pi_source_commit",
        "pi_patch_set_sha256",
    }
    if set(value) != expected:
        raise CanonicalRequestValidationError("runtime shape is invalid")
    for key in ("pi_coding_agent_version", "pi_ai_version"):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise CanonicalRequestValidationError(
                f"runtime {key} must be a non-empty string"
            )
    source_commit = value.get("pi_source_commit")
    if not isinstance(source_commit, str) or not _SOURCE_COMMIT_PATTERN.fullmatch(
        source_commit
    ):
        raise CanonicalRequestValidationError("runtime pi_source_commit is invalid")
    patch_hash = value.get("pi_patch_set_sha256")
    if not isinstance(patch_hash, str) or not _SHA256_PATTERN.fullmatch(patch_hash):
        raise CanonicalRequestValidationError(
            "runtime pi_patch_set_sha256 is invalid"
        )


def _semantic_request(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError("semantic_request must be an object")
    if set(value) != {"model", "context", "options"}:
        raise CanonicalRequestValidationError("semantic_request shape is invalid")
    _semantic_model(value.get("model"))
    _semantic_context(value.get("context"))
    _semantic_options(value.get("options"))
    return value


def _semantic_model(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "semantic_request.model must be an object"
        )
    if set(value) != {"provider", "api", "id"}:
        raise CanonicalRequestValidationError("semantic_request.model shape is invalid")
    _required_string(value, "provider")
    _required_string(value, "api")
    _required_string(value, "id")


def _semantic_context(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "semantic_request.context must be an object"
        )
    if set(value) != {"system_prompt", "messages", "tools"}:
        raise CanonicalRequestValidationError(
            "semantic_request.context shape is invalid"
        )
    system_prompt = value.get("system_prompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise CanonicalRequestValidationError(
            "semantic_request.context.system_prompt is invalid"
        )
    messages = value.get("messages")
    tools = value.get("tools")
    if not isinstance(messages, list):
        raise CanonicalRequestValidationError(
            "semantic_request.context.messages must be an array"
        )
    if not isinstance(tools, list):
        raise CanonicalRequestValidationError(
            "semantic_request.context.tools must be an array"
        )
    for message in messages:
        _semantic_message(message)
    for tool in tools:
        _semantic_tool(tool)


def _semantic_message(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "semantic_request message must be an object"
        )
    role = value.get("role")
    if role == "user":
        if set(value) != {"role", "content"}:
            raise CanonicalRequestValidationError(
                "semantic_request user message shape is invalid"
            )
        _semantic_user_content(value.get("content"))
        return
    if role == "assistant":
        if set(value) != {"role", "content"}:
            raise CanonicalRequestValidationError(
                "semantic_request assistant message shape is invalid"
            )
        content = value.get("content")
        if not isinstance(content, list):
            raise CanonicalRequestValidationError("assistant.content must be an array")
        for block in content:
            _semantic_assistant_content_block(block)
        return
    if role == "toolResult":
        expected = {
            "role",
            "toolCallId",
            "toolName",
            "content",
            "details",
            "isError",
        }
        if set(value) != expected:
            raise CanonicalRequestValidationError(
                "semantic_request tool result message shape is invalid"
            )
        _required_string(value, "toolCallId")
        _required_string(value, "toolName")
        _semantic_user_content(value.get("content"))
        _validate_public_json_leaf(value.get("details"), "toolResult.details")
        if not isinstance(value.get("isError"), bool):
            raise CanonicalRequestValidationError("toolResult.isError must be boolean")
        return
    raise CanonicalRequestValidationError("semantic_request message role is invalid")


def _semantic_user_content(value: object) -> None:
    if not isinstance(value, list):
        raise CanonicalRequestValidationError("user content must be an array")
    for block in value:
        _semantic_user_content_block(block)


def _semantic_user_content_block(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError("user content block must be an object")
    block_type = value.get("type")
    if block_type == "text":
        if set(value) != {"type", "text"}:
            raise CanonicalRequestValidationError("text content shape is invalid")
        text = value.get("text")
        if not isinstance(text, str):
            raise CanonicalRequestValidationError("text.text must be a string")
        return
    if block_type == "image":
        if set(value) != {"type", "data", "mimeType"}:
            raise CanonicalRequestValidationError("image content shape is invalid")
        _required_string(value, "data")
        _required_string(value, "mimeType")
        return
    raise CanonicalRequestValidationError("user content block type is invalid")


def _semantic_assistant_content_block(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "assistant content block must be an object"
        )
    block_type = value.get("type")
    if block_type == "text":
        if set(value) != {"type", "text"}:
            raise CanonicalRequestValidationError(
                "assistant text content shape is invalid"
            )
        text = value.get("text")
        if not isinstance(text, str):
            raise CanonicalRequestValidationError("text.text must be a string")
        return
    if block_type == "thinking":
        if set(value) != {"type", "redacted"} or value.get("redacted") is not True:
            raise CanonicalRequestValidationError(
                "assistant thinking content shape is invalid"
            )
        return
    if block_type == "toolCall":
        if set(value) != {"type", "id", "name", "arguments"}:
            raise CanonicalRequestValidationError(
                "assistant toolCall content shape is invalid"
            )
        _required_string(value, "id")
        _required_string(value, "name")
        arguments = value.get("arguments")
        if not isinstance(arguments, Mapping):
            raise CanonicalRequestValidationError(
                "toolCall.arguments must be an object"
            )
        _validate_public_json_leaf(arguments, "toolCall.arguments")
        return
    raise CanonicalRequestValidationError("assistant content block type is invalid")


def _semantic_tool(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError("semantic_request tool must be an object")
    if set(value) != {"name", "description", "parameters"}:
        raise CanonicalRequestValidationError("semantic_request tool shape is invalid")
    _required_string(value, "name")
    if not isinstance(value.get("description"), str):
        raise CanonicalRequestValidationError("tool.description must be a string")
    parameters = value.get("parameters")
    if not isinstance(parameters, Mapping):
        raise CanonicalRequestValidationError("tool.parameters must be an object")
    _validate_public_json_leaf(parameters, "tool.parameters")


def _semantic_options(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "semantic_request.options must be an object"
        )
    if set(value) - _PUBLIC_OPTION_KEYS:
        raise CanonicalRequestValidationError(
            "semantic_request.options has unknown fields"
        )
    for key, item in value.items():
        if key == "reasoning":
            if item not in _REASONING_VALUES:
                raise CanonicalRequestValidationError("options.reasoning is invalid")
        elif key == "transport":
            if item not in _TRANSPORT_VALUES:
                raise CanonicalRequestValidationError("options.transport is invalid")
        elif key == "cacheRetention":
            if item not in _CACHE_RETENTION_VALUES:
                raise CanonicalRequestValidationError(
                    "options.cacheRetention is invalid"
                )
        elif key == "thinkingBudgets":
            _semantic_thinking_budgets(item)
        elif key in _NUMERIC_OPTION_KEYS:
            _nonnegative_number(item, f"options.{key}")


def _semantic_thinking_budgets(value: object) -> None:
    if not isinstance(value, Mapping):
        raise CanonicalRequestValidationError(
            "options.thinkingBudgets must be an object"
        )
    if set(value) - _THINKING_BUDGET_KEYS:
        raise CanonicalRequestValidationError(
            "options.thinkingBudgets has unknown fields"
        )
    for key, item in value.items():
        _nonnegative_number(item, f"options.thinkingBudgets.{key}")


def _source_sequences(document: Mapping[str, Any]) -> tuple[int, ...]:
    values = document.get("source_event_sequences")
    if not isinstance(values, list) or not values or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 1
        for value in values
    ):
        raise CanonicalRequestValidationError(
            "source_event_sequences must contain positive integers"
        )
    if values != sorted(set(values)):
        raise CanonicalRequestValidationError(
            "source_event_sequences must be strictly increasing"
        )
    return tuple(values)


def _required_string(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise CanonicalRequestValidationError(f"{key} must be a non-empty string")
    return value


def _required_positive_int(document: Mapping[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CanonicalRequestValidationError(f"{key} must be a positive integer")
    return value


def _validate_public_json_leaf(value: object, path: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise CanonicalRequestValidationError(
                f"{path} contains a non-finite number"
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_public_json_leaf(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalRequestValidationError(
                    f"{path} contains a non-string key"
                )
            _validate_public_json_leaf(item, f"{path}.{key}")
        return
    raise CanonicalRequestValidationError(f"{path} contains a non-JSON value")


def _nonnegative_number(value: object, name: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        or not math.isfinite(value)
    ):
        raise CanonicalRequestValidationError(f"{name} must be a nonnegative number")


def _sort_json(value: object) -> object:
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    return value
