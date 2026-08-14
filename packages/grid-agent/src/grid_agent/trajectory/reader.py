"""Fail-closed reader for native trajectory event logs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from grid_agent.trajectory.canonical import canonical_json_bytes, sha256_ref
from grid_agent.trajectory.events import PAYLOAD_MODELS, ZERO_PREDECESSOR_HASH, RunEvent


_REQUIRED_EVENT_MEMBERS = frozenset(
    {
        "schema_version",
        "analysis_id",
        "sequence",
        "timestamp",
        "event_type",
        "previous_event_hash",
        "event_hash",
        "scope",
        "causation",
        "source",
        "context",
        "refs",
        "payload",
    }
)


ReplayFailureCode = Literal[
    "malformed_json",
    "invalid_event",
    "sequence_gap",
    "previous_hash_mismatch",
    "event_hash_mismatch",
    "unknown_event",
]


@dataclass(frozen=True, slots=True)
class ReplayFailure:
    """The first line that cannot extend a trusted replay prefix."""

    line_number: int
    code: ReplayFailureCode
    message: str


@dataclass(frozen=True, slots=True)
class ReplayPrefix:
    """Trusted event prefix and, if applicable, its first failure."""

    events: tuple[RunEvent, ...]
    failure: ReplayFailure | None


class RunEventReader:
    """Verify a JSONL event hash chain without trusting any invalid suffix."""

    def __init__(self, events_path: Path) -> None:
        self.events_path = events_path

    def read_prefix(self) -> ReplayPrefix:
        if not self.events_path.exists():
            return ReplayPrefix((), None)

        trusted: list[RunEvent] = []
        previous_hash = ZERO_PREDECESSOR_HASH
        for line_number, raw in enumerate(
            self.events_path.read_bytes().splitlines(), start=1
        ):
            try:
                decoded = json.loads(raw, parse_constant=_reject_non_finite_constant)
            except (ValueError, UnicodeDecodeError) as exc:
                return self._failure(trusted, line_number, "malformed_json", str(exc))

            if not _has_only_finite_numbers(decoded):
                return self._failure(
                    trusted,
                    line_number,
                    "invalid_event",
                    "event contains a non-finite number",
                )
            if not isinstance(decoded, Mapping):
                return self._failure(
                    trusted, line_number, "invalid_event", "event line must be a JSON object"
                )
            event_type = decoded.get("event_type")
            if isinstance(event_type, str) and event_type not in PAYLOAD_MODELS:
                return self._failure(
                    trusted,
                    line_number,
                    "unknown_event",
                    f"unknown event type: {event_type!r}",
                )
            missing_members = _REQUIRED_EVENT_MEMBERS.difference(decoded)
            if missing_members:
                return self._failure(
                    trusted,
                    line_number,
                    "invalid_event",
                    f"event envelope is missing: {', '.join(sorted(missing_members))}",
                )
            try:
                event = RunEvent.model_validate(decoded)
            except (ValidationError, ValueError) as exc:
                return self._failure(trusted, line_number, "invalid_event", str(exc))
            if not _matches_native_json(decoded, event.model_dump(mode="json")):
                return self._failure(
                    trusted,
                    line_number,
                    "invalid_event",
                    "event values do not use the required JSON-native types",
                )
            if event.sequence != line_number:
                return self._failure(
                    trusted,
                    line_number,
                    "sequence_gap",
                    f"expected {line_number}, got {event.sequence}",
                )
            if event.previous_event_hash != previous_hash:
                return self._failure(
                    trusted,
                    line_number,
                    "previous_hash_mismatch",
                    "previous hash does not match trusted prefix",
                )
            if recompute_event_hash(decoded) != event.event_hash:
                return self._failure(
                    trusted,
                    line_number,
                    "event_hash_mismatch",
                    "event content does not match event_hash",
                )
            trusted.append(event)
            previous_hash = event.event_hash
        return ReplayPrefix(tuple(trusted), None)

    @staticmethod
    def _failure(
        trusted: list[RunEvent],
        line_number: int,
        code: ReplayFailureCode,
        message: str,
    ) -> ReplayPrefix:
        return ReplayPrefix(tuple(trusted), ReplayFailure(line_number, code, message))


def _reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not permitted: {value}")


def _has_only_finite_numbers(value: object) -> bool:
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, Mapping):
        return all(_has_only_finite_numbers(item) for item in value.values())
    if isinstance(value, list):
        return all(_has_only_finite_numbers(item) for item in value)
    return True


def _matches_native_json(decoded: object, validated: object) -> bool:
    if type(decoded) is not type(validated):
        return False
    if isinstance(decoded, Mapping) and isinstance(validated, Mapping):
        return decoded.keys() == validated.keys() and all(
            _matches_native_json(decoded[key], validated[key]) for key in decoded
        )
    if isinstance(decoded, list) and isinstance(validated, list):
        return len(decoded) == len(validated) and all(
            _matches_native_json(raw_item, validated_item)
            for raw_item, validated_item in zip(decoded, validated, strict=True)
        )
    return decoded == validated


def recompute_event_hash(event: RunEvent | Mapping[str, object]) -> str:
    """Return the canonical hash for an event's content excluding its hash field."""
    content = event.model_dump(mode="json") if isinstance(event, RunEvent) else dict(event)
    del content["event_hash"]
    return sha256_ref(canonical_json_bytes(content))
