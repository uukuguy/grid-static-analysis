"""Durable, append-only recorder for native trajectory events."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import (
    ZERO_PREDECESSOR_HASH,
    EventDraft,
    RunEvent,
    build_event,
)


class RecorderIntegrityError(RuntimeError):
    """Raised when a draft is unsafe or a durable append cannot complete."""


_PROHIBITED_FIELD_TOKENS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "reasoning",
        "chain_of_thought",
    }
)
_HIDDEN_REASONING = re.compile(r"\b(?:chain[- ]of[- ]thought|hidden reasoning)\b", re.IGNORECASE)


class RunEventRecorder:
    """Append validated events before notifying best-effort subscribers."""

    def __init__(
        self,
        events_path: Path,
        analysis_id: str,
        *,
        secret_values: Iterable[str] = (),
        subscribers: Iterable[Callable[[RunEvent], None]] = (),
    ) -> None:
        if not analysis_id:
            raise ValueError("analysis_id must not be empty")
        self.events_path = events_path
        self.analysis_id = analysis_id
        self._secret_values = frozenset(value for value in secret_values if value)
        self._subscribers = tuple(subscribers)
        self._subscriber_failures: list[str] = []
        self._next_sequence = 1
        self._previous_hash = ZERO_PREDECESSOR_HASH
        self._closed = False

    def append(self, draft: EventDraft) -> RunEvent:
        """Durably append *draft* and then publish the recorded event."""
        if self._closed:
            raise RecorderIntegrityError("trajectory recorder is closed")
        self._reject_prohibited_content(draft.model_dump(mode="json"))
        event = build_event(
            draft,
            analysis_id=self.analysis_id,
            sequence=self._next_sequence,
            timestamp=datetime.now(UTC),
            previous_event_hash=self._previous_hash,
        )
        encoded_event = canonical_json_bytes(event.model_dump(mode="json"))
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("ab") as stream:
                written = stream.write(encoded_event)
                if written != len(encoded_event):
                    raise OSError(
                        f"short write: expected {len(encoded_event)} bytes, wrote {written}"
                    )
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            self._closed = True
            raise RecorderIntegrityError(f"trajectory append failed: {exc}") from exc

        self._next_sequence += 1
        self._previous_hash = event.event_hash
        for subscriber in self._subscribers:
            try:
                subscriber(event)
            except Exception as exc:  # Subscribers are explicitly best effort.
                self._subscriber_failures.append(f"{type(exc).__name__}: {exc}")
        return event

    def close(self) -> None:
        """Prevent subsequent appends."""
        self._closed = True

    def _reject_prohibited_content(self, value: object) -> None:
        if self._contains_prohibited_content(value):
            raise RecorderIntegrityError("prohibited content in trajectory event")

    def _contains_prohibited_content(self, value: object) -> bool:
        if isinstance(value, str):
            return (
                any(secret in value for secret in self._secret_values)
                or _HIDDEN_REASONING.search(value) is not None
            )
        if isinstance(value, Mapping):
            return any(
                self._is_prohibited_field_name(key)
                or self._contains_prohibited_content(item)
                for key, item in value.items()
            )
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return any(self._contains_prohibited_content(item) for item in value)
        return False

    @staticmethod
    def _is_prohibited_field_name(value: object) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.lower().replace("-", "_").replace(" ", "_")
        return any(token in normalized for token in _PROHIBITED_FIELD_TOKENS)
