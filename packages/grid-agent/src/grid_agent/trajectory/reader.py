"""Fail-closed reader for native trajectory event logs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from grid_agent.trajectory.canonical import canonical_json_bytes, sha256_ref
from grid_agent.trajectory.events import PAYLOAD_MODELS, ZERO_PREDECESSOR_HASH, RunEvent


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
                decoded = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return self._failure(trusted, line_number, "malformed_json", str(exc))

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
            try:
                event = RunEvent.model_validate(decoded)
            except (ValidationError, ValueError) as exc:
                return self._failure(trusted, line_number, "invalid_event", str(exc))
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
            if recompute_event_hash(event) != event.event_hash:
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


def recompute_event_hash(event: RunEvent) -> str:
    """Return the canonical hash for an event's content excluding its hash field."""
    content = event.model_dump(mode="json")
    del content["event_hash"]
    return sha256_ref(canonical_json_bytes(content))
