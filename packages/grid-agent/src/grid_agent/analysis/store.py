from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ValidationError

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent, ContextEventDraft
from grid_agent.analysis.reducer import ContextTransitionError, initial_context, reduce_context
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.events import RunEvent


ContextTransitionCommit = Callable[
    [ContextEventDraft, AnalysisContext, AnalysisContext], RunEvent
]


class ContextStoreError(RuntimeError):
    """Raised when the durable analysis context store detects corrupted state."""


class AnalysisContextStore:
    def __init__(
        self,
        workspace: AnalysisWorkspace,
        snapshot: AnalysisContext,
        transition_commit: ContextTransitionCommit | None = None,
    ) -> None:
        self._workspace = workspace
        self._snapshot = snapshot
        self._transition_commit = transition_commit

    @property
    def snapshot(self) -> AnalysisContext:
        return self._snapshot

    @classmethod
    def initialize(
        cls,
        workspace: AnalysisWorkspace,
        *,
        input_record: Mapping[str, Any] | BaseModel,
        runtime_record: Mapping[str, Any] | BaseModel,
        transition_commit: ContextTransitionCommit | None = None,
    ) -> AnalysisContextStore:
        if workspace.context_events_path.exists() and workspace.context_events_path.read_text(encoding="utf-8"):
            raise ContextStoreError(f"context ledger already exists: {workspace.context_events_path}")

        input_payload = _model_payload(input_record)
        runtime_payload = _model_payload(runtime_record)
        genesis = initial_context(workspace.analysis_id, input_payload, runtime_payload)
        store = cls(workspace, genesis, transition_commit)
        store.append(
            ContextEventDraft(
                event_type="analysis.started",
                payload={"input": input_payload, "runtime": runtime_payload},
            )
        )
        return store

    def append(
        self,
        draft: ContextEventDraft,
        *,
        integrity: Literal["verified", "diagnostic"] = "verified",
    ) -> AnalysisContextEvent:
        if integrity not in {"verified", "diagnostic"}:
            raise ContextStoreError(f"unsupported integrity value: {integrity}")

        previous = self._snapshot
        try:
            next_snapshot = reduce_context(previous, draft)
        except (ContextTransitionError, ValidationError) as exc:
            raise ContextStoreError(str(exc)) from exc

        trace_sequence = draft.trace_sequence
        if self._transition_commit is not None:
            try:
                native_event = self._transition_commit(
                    draft, previous, next_snapshot
                )
            except Exception as exc:
                raise ContextStoreError(
                    f"native trajectory commit failed: {exc}"
                ) from exc
            trace_sequence = native_event.sequence

        try:
            event = AnalysisContextEvent(
                **draft.model_dump(mode="json", exclude={"trace_sequence"}),
                trace_sequence=trace_sequence,
                analysis_id=previous.analysis_id,
                sequence=next_snapshot.revision,
                previous_revision=previous.revision,
                previous_state_hash=previous.state_hash,
                next_revision=next_snapshot.revision,
                next_state_hash=next_snapshot.state_hash,
                integrity=integrity,
            )
        except ValidationError as exc:
            raise ContextStoreError(str(exc)) from exc

        _append_jsonl_fsync(self._workspace.context_events_path, event.model_dump(mode="json"))
        _write_json_atomic(self._workspace.context_snapshot_path, next_snapshot.model_dump(mode="json"))
        self._snapshot = next_snapshot
        return event

    @classmethod
    def replay(cls, ledger_path: Path) -> AnalysisContext:
        state: AnalysisContext | None = None
        expected_sequence = 1

        if not ledger_path.exists():
            raise ContextStoreError(f"context ledger does not exist: {ledger_path}")

        for line_number, raw_line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
            if raw_line == "":
                raise ContextStoreError(f"malformed ledger line {line_number}: blank line")
            try:
                payload = json.loads(raw_line)
                event = AnalysisContextEvent.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ContextStoreError(f"malformed ledger line {line_number}") from exc

            if event.sequence != expected_sequence:
                raise ContextStoreError(
                    f"non-contiguous event sequence at line {line_number}: "
                    f"expected {expected_sequence}, got {event.sequence}"
                )
            if event.next_revision != event.sequence:
                raise ContextStoreError(f"event next_revision must match sequence at line {line_number}")

            if state is None:
                state = _genesis_from_first_event(event, line_number=line_number)

            if event.analysis_id != state.analysis_id:
                raise ContextStoreError(f"analysis_id changed at line {line_number}")
            if event.previous_revision != state.revision:
                raise ContextStoreError(
                    f"previous_revision mismatch at line {line_number}: "
                    f"expected {state.revision}, got {event.previous_revision}"
                )
            if event.previous_state_hash != state.state_hash:
                raise ContextStoreError(
                    f"previous_state_hash mismatch at line {line_number}: "
                    f"expected {state.state_hash}, got {event.previous_state_hash}"
                )

            draft = ContextEventDraft(
                event_type=event.event_type,
                turn_id=event.turn_id,
                capability=event.capability,
                trace_sequence=event.trace_sequence,
                timestamp=event.timestamp,
                payload=event.payload,
            )
            try:
                next_state = reduce_context(state, draft)
            except ContextTransitionError as exc:
                raise ContextStoreError(f"invalid transition at line {line_number}: {exc}") from exc

            if event.next_revision != next_state.revision:
                raise ContextStoreError(f"next_revision mismatch at line {line_number}")
            if event.next_state_hash != next_state.state_hash:
                raise ContextStoreError(f"next_state_hash mismatch at line {line_number}")

            state = next_state
            expected_sequence += 1

        if state is None:
            raise ContextStoreError(f"context ledger is empty: {ledger_path}")
        return state

    def verify_materialized_snapshot(self) -> AnalysisContext:
        try:
            materialized = AnalysisContext.model_validate(
                json.loads(self._workspace.context_snapshot_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ContextStoreError(f"materialized snapshot is unreadable: {self._workspace.context_snapshot_path}") from exc

        replayed = self.replay(self._workspace.context_events_path)
        if materialized != self._snapshot:
            raise ContextStoreError("materialized snapshot does not match in-memory snapshot")
        if materialized != replayed:
            raise ContextStoreError("materialized snapshot does not match replayed ledger")
        return materialized


def _genesis_from_first_event(event: AnalysisContextEvent, *, line_number: int) -> AnalysisContext:
    if event.sequence != 1 or event.event_type != "analysis.started":
        raise ContextStoreError("context ledger must begin with analysis.started sequence 1")
    if event.previous_revision != 0:
        raise ContextStoreError(f"analysis.started previous_revision must be 0 at line {line_number}")
    if not isinstance(event.payload.get("input"), dict) or not isinstance(event.payload.get("runtime"), dict):
        raise ContextStoreError(f"analysis.started payload must contain complete input and runtime records at line {line_number}")
    return initial_context(event.analysis_id, event.payload["input"], event.payload["runtime"])


def _model_payload(record: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="json")
    return dict(record)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _append_jsonl_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(_canonical_json(payload))
        stream.flush()
        os.fsync(stream.fileno())


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
