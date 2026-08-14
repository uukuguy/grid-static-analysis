"""Durable, append-only recorder for native trajectory events."""

from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import BinaryIO

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import (
    ZERO_PREDECESSOR_HASH,
    EventDraft,
    RunEvent,
    build_event,
)


class RecorderIntegrityError(RuntimeError):
    """Raised when a draft is unsafe or a durable append cannot complete."""


_PROHIBITED_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "chain_of_thought",
        "client_secret",
        "credential",
        "credentials",
        "hidden_reasoning",
        "password",
        "reasoning",
        "refresh_token",
        "secret",
        "token",
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
        self._append_lock = Lock()
        self._lock_stream: BinaryIO | None = None
        self._closed = True
        self._claim_ownership()

    def append(self, draft: EventDraft) -> RunEvent:
        """Durably append *draft* and then publish the recorded event."""
        with self._append_lock:
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
                with self.events_path.open("ab") as stream:
                    written = stream.write(encoded_event)
                    if written != len(encoded_event):
                        raise OSError(
                            f"short write: expected {len(encoded_event)} bytes, "
                            f"wrote {written}"
                        )
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                self._close_locked()
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
        with self._append_lock:
            self._close_locked()

    def _claim_ownership(self) -> None:
        lock_path = self.events_path.with_name(f"{self.events_path.name}.lock")
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            lock_stream = lock_path.open("a+b")
        except OSError as exc:
            raise RecorderIntegrityError(
                f"trajectory ownership failed: {exc}"
            ) from exc
        try:
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RecorderIntegrityError(
                    f"trajectory path is already owned: {self.events_path}"
                ) from None
            if self.events_path.exists() and self.events_path.stat().st_size > 0:
                raise RecorderIntegrityError(
                    f"trajectory path already contains events: {self.events_path}"
                )
        except RecorderIntegrityError:
            self._release_lock_stream(lock_stream)
            raise
        except OSError as exc:
            self._release_lock_stream(lock_stream)
            raise RecorderIntegrityError(
                f"trajectory ownership failed: {exc}"
            ) from exc
        self._lock_stream = lock_stream
        self._closed = False

    def _close_locked(self) -> None:
        self._closed = True
        lock_stream = self._lock_stream
        self._lock_stream = None
        if lock_stream is None:
            return
        self._release_lock_stream(lock_stream)

    @staticmethod
    def _release_lock_stream(lock_stream: BinaryIO) -> None:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            lock_stream.close()

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
        return normalized in _PROHIBITED_FIELD_NAMES
