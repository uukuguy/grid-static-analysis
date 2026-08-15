"""Native-first projection of compatibility analysis context transitions."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from grid_agent.analysis.models import AnalysisContext, ContextEventDraft
from grid_agent.trajectory.artifacts import (
    ArtifactIntegrityError,
    ArtifactPointer,
    ImmutableArtifactRegistry,
)
from grid_agent.trajectory.events import (
    ContextBoundary,
    EventDraft,
    EventRefs,
    EventType,
    RunEvent,
    RunScope,
)
from grid_agent.trajectory.recorder import RunEventRecorder


CONTEXT_TO_NATIVE: Mapping[str, EventType] = {
    "analysis.started": "analysis.started",
    "analysis.completed": "analysis.completed",
    "analysis.failed": "analysis.failed",
    "turn.started": "turn.started",
    "turn.completed": "turn.completed",
    "tool.failed": "tool.failed",
    "answer.submitted": "answer.submitted",
    "audit.diagnostic.recorded": "audit.diagnostic.recorded",
}


class ContextBridgeWorkspace(Protocol):
    @property
    def root_path(self) -> Path: ...

    @property
    def trajectory_capture_state_path(self) -> Path: ...


class NativeContextBridge:
    """Commit native events before their compatibility ledger projections."""

    def __init__(
        self,
        recorder: RunEventRecorder,
        artifacts: ImmutableArtifactRegistry,
        workspace: ContextBridgeWorkspace,
    ) -> None:
        self.recorder = recorder
        self.artifacts = artifacts
        self.workspace = workspace
        self.on_native_commit: Callable[[RunEvent], None] | None = None

    def commit(
        self,
        draft: ContextEventDraft,
        before: AnalysisContext,
        after: AnalysisContext,
    ) -> RunEvent:
        event_type: EventType = CONTEXT_TO_NATIVE.get(
            draft.event_type, "context.projected"
        )
        answer_pointer = (
            self._admit_answer(draft)
            if event_type == "answer.submitted"
            else None
        )
        event = self.recorder.append(
            EventDraft(
                event_type=event_type,
                scope=(
                    RunScope(turn_id=draft.turn_id)
                    if draft.turn_id is not None
                    else RunScope()
                ),
                context=ContextBoundary(
                    before_revision=before.revision,
                    after_revision=after.revision,
                ),
                payload=self._payload(
                    event_type, draft, after, answer_pointer=answer_pointer
                ),
                refs=self._refs(draft, answer_pointer=answer_pointer),
            )
        )
        self._finish_commit(event, after)
        return event

    def record_injection(
        self, context_view_path: Path, context: AnalysisContext
    ) -> RunEvent:
        source = Path(context_view_path).read_bytes()
        try:
            document = json.loads(source)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                "context view is not readable JSON"
            ) from exc
        if not isinstance(document, Mapping):
            raise ArtifactIntegrityError("context view must be a JSON object")
        if (
            document.get("revision") != context.revision
            or document.get("state_hash") != context.state_hash
        ):
            raise ArtifactIntegrityError(
                "context view does not match the injected context"
            )

        identity = f"r{context.revision}-{context.state_hash}"
        pointer = self.artifacts.write_json(
            "context-view", identity, dict(document)
        )
        immutable_path = self.artifacts.verify(pointer)
        if immutable_path.read_bytes() != source:
            raise ArtifactIntegrityError(
                "context view bytes are not canonical and exact"
            )

        event = self.recorder.append(
            EventDraft(
                event_type="context.injected",
                context=ContextBoundary(
                    before_revision=context.revision,
                    after_revision=context.revision,
                ),
                refs=EventRefs(produced=(pointer.ref,)),
                payload={
                    "revision": context.revision,
                    "state_hash": context.state_hash,
                    "artifact_ref": pointer.ref,
                },
            )
        )
        self._finish_commit(event, context)
        return event

    def _finish_commit(
        self, event: RunEvent, context: AnalysisContext
    ) -> None:
        _write_json_atomic(
            self.workspace.trajectory_capture_state_path,
            {
                "source_event_sequences": [event.sequence],
                "context_revision": context.revision,
                "context_state_hash": context.state_hash,
            },
        )
        if self.on_native_commit is not None:
            self.on_native_commit(event)

    def _admit_answer(
        self, draft: ContextEventDraft
    ) -> ArtifactPointer:
        if draft.turn_id is None:
            raise ArtifactIntegrityError("answer submission requires turn_id")
        relative_path = draft.payload.get("answer_path")
        if not isinstance(relative_path, str) or not relative_path:
            raise ArtifactIntegrityError(
                "answer submission requires answer_path"
            )
        answer_path = self.workspace.root_path / relative_path
        return self.artifacts.register_existing(
            "answer", answer_path.parent.name, answer_path
        )

    @staticmethod
    def _payload(
        event_type: str,
        draft: ContextEventDraft,
        after: AnalysisContext,
        *,
        answer_pointer: ArtifactPointer | None,
    ) -> dict[str, Any]:
        payload = draft.payload
        if event_type == "analysis.started":
            return {}
        if event_type == "analysis.completed":
            return {
                "completed_turns": int(payload.get("completed_turns", 0)),
                "total_turns": int(payload.get("total_turns", 0)),
            }
        if event_type == "analysis.failed":
            return {
                "error_type": str(payload.get("error_type", "analysis_error")),
                "message": str(payload.get("message", payload.get("error", "analysis failed"))),
            }
        if event_type == "turn.started":
            return {
                "ordinal": int(payload["ordinal"]),
                "instruction_sha256": str(payload["instruction_sha256"]),
            }
        if event_type == "turn.completed":
            return {
                "status": payload.get("status", "failed"),
                "duration_seconds": payload.get("duration_seconds"),
            }
        if event_type == "tool.failed":
            result: dict[str, Any] = {
                "capability": draft.capability or "unknown",
                "ok": False,
            }
            artifact_ref = payload.get("artifact_ref")
            if isinstance(artifact_ref, str) and artifact_ref:
                result["artifact_ref"] = artifact_ref
            return result
        if event_type == "answer.submitted":
            if answer_pointer is None:
                raise ArtifactIntegrityError(
                    "answer submission artifact was not admitted"
                )
            return {
                "submission_id": str(
                    payload.get("submission_id", draft.turn_id)
                ),
                "artifact_ref": answer_pointer.ref,
                "result_refs": _string_values(payload.get("result_refs")),
                "evidence_refs": _string_values(
                    payload.get("claim_evidence_refs", payload.get("evidence_refs"))
                ),
            }
        if event_type == "audit.diagnostic.recorded":
            severity = payload.get("severity", "warning")
            return {
                "severity": severity,
                "category": str(payload.get("category", "analysis-context")),
                "message": str(payload.get("message", "analysis diagnostic")),
            }
        return {
            "revision": after.revision,
            "state_hash": after.state_hash,
            "artifact_ref": None,
        }

    @staticmethod
    def _refs(
        draft: ContextEventDraft,
        *,
        answer_pointer: ArtifactPointer | None,
    ) -> EventRefs:
        consumed = _collect_references(
            draft.payload, "consumed_refs", "result_refs"
        )
        produced = _collect_references(draft.payload, "produced_refs")
        evidence = _collect_references(
            draft.payload, "evidence_refs", "claim_evidence_refs"
        )
        if answer_pointer is not None:
            produced = (*produced, answer_pointer.ref)
        return EventRefs(
            consumed=tuple(dict.fromkeys(consumed)),
            produced=tuple(dict.fromkeys(produced)),
            evidence=tuple(dict.fromkeys(evidence)),
        )


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _collect_references(
    payload: Mapping[str, Any], *keys: str
) -> tuple[str, ...]:
    references: list[str] = []
    for key in keys:
        references.extend(_string_values(payload.get(key)))
    refs = payload.get("refs")
    if isinstance(refs, Mapping):
        for key in keys:
            references.extend(_string_values(refs.get(key)))
    elif "consumed_refs" in keys:
        references.extend(_string_values(refs))
    return tuple(references)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
