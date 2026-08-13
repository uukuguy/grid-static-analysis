from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from grid_agent.analysis.integrity import ReferenceDiagnostic
from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.analysis.workspace import AnalysisWorkspace


AuditCallback = Callable[[tuple[str, ...], tuple[str, ...]], tuple[ReferenceDiagnostic, ...]]


class AnswerDraftError(RuntimeError):
    """Raised when a submitted answer draft cannot be accepted for the active turn."""


class StaleAnswerDraftError(AnswerDraftError):
    """Raised when a draft was bound to a different turn id or nonce."""


@dataclass(frozen=True, slots=True)
class ActiveTurnHandle:
    ordinal: int
    turn_id: str
    instruction: str
    instruction_sha256: str
    turn_nonce: str
    started_monotonic: float


@dataclass(frozen=True, slots=True)
class FinalizedTurn:
    turn_id: str
    status: Literal["success", "limited", "failed"]
    answer_output: str
    answer_path: Path | None
    audit_diagnostics: tuple[ReferenceDiagnostic, ...]
    error: str | None


class TurnController:
    def __init__(
        self,
        workspace: AnalysisWorkspace,
        store: AnalysisContextStore,
        *,
        audit_callback: AuditCallback,
    ) -> None:
        self._workspace = workspace
        self._store = store
        self._audit_callback = audit_callback

    def start(self, ordinal: int, instruction: str) -> ActiveTurnHandle:
        turn_nonce = secrets.token_urlsafe(32)
        handle = ActiveTurnHandle(
            ordinal=ordinal,
            turn_id=f"{self._workspace.analysis_id}-t{ordinal:03d}",
            instruction=instruction,
            instruction_sha256=sha256(instruction.encode("utf-8")).hexdigest(),
            turn_nonce=turn_nonce,
            started_monotonic=time.monotonic(),
        )
        self._clear_active_answer_draft()
        _write_json_atomic(
            self._workspace.active_turn_path,
            {
                "schema_version": "grid-agent-active-turn/1.0",
                "analysis_id": self._workspace.analysis_id,
                "ordinal": handle.ordinal,
                "turn_id": handle.turn_id,
                "instruction": handle.instruction,
                "instruction_sha256": handle.instruction_sha256,
                "turn_nonce": handle.turn_nonce,
                "started_monotonic": handle.started_monotonic,
            },
        )
        self._store.append(
            ContextEventDraft(
                event_type="turn.started",
                turn_id=handle.turn_id,
                payload={
                    "ordinal": handle.ordinal,
                    "instruction": handle.instruction,
                    "instruction_sha256": handle.instruction_sha256,
                    "nonce_sha256": _sha256_text(handle.turn_nonce),
                },
            )
        )
        return handle

    def finalize(self, handle: ActiveTurnHandle, *, duration_seconds: float) -> FinalizedTurn:
        if not self._workspace.active_answer_draft_path.is_file():
            return self.fail(
                handle,
                error="grid_submit_answer did not create an answer draft",
                duration_seconds=duration_seconds,
            )

        raw_draft = self._workspace.active_answer_draft_path.read_bytes()
        draft = _load_answer_draft(raw_draft)
        _require_current_turn_binding(draft, handle)
        answer = _require_non_empty_string(draft, "answer_output")
        claim_evidence_refs = _require_string_list(draft, "claim_evidence_refs")
        result_refs = _require_string_list(draft, "result_refs")
        diagnostics = self._audit_answer(claim_evidence_refs, result_refs)

        turn_path = self._workspace.turn_path(handle.ordinal)
        archived_draft_path = turn_path / "answer-draft.json"
        _write_bytes_atomic(archived_draft_path, raw_draft)
        _write_audit(turn_path / "answer-audit.json", diagnostics)

        envelope = {"question_id": handle.turn_id, "answer_output": answer}
        answer_path = turn_path / "answer.json"
        answer_bytes = _write_json_atomic(answer_path, envelope)
        _append_jsonl_fsync(self._workspace.answers_path, envelope)

        for diagnostic in diagnostics:
            self._record_audit_diagnostic(handle, diagnostic)
        self._store.append(
            ContextEventDraft(
                event_type="turn.completed",
                turn_id=handle.turn_id,
                payload={
                    "status": "success",
                    "answer_path": str(answer_path.relative_to(self._workspace.root_path)),
                    "answer_sha256": sha256(answer_bytes).hexdigest(),
                    "duration_seconds": duration_seconds,
                },
            )
        )
        self._remove_active_turn()
        return FinalizedTurn(
            turn_id=handle.turn_id,
            status="success",
            answer_output=answer,
            answer_path=answer_path,
            audit_diagnostics=diagnostics,
            error=None,
        )

    def fail(self, handle: ActiveTurnHandle, *, error: str, duration_seconds: float) -> FinalizedTurn:
        answer = f"执行限制 / execution limitation: {error}"
        self._store.append(
            ContextEventDraft(
                event_type="limitation.recorded",
                turn_id=handle.turn_id,
                payload={
                    "limitation_ref": _limitation_ref(handle.turn_id, error),
                    "message": error,
                    "refs": [],
                },
            ),
            integrity="diagnostic",
        )
        self._store.append(
            ContextEventDraft(
                event_type="turn.completed",
                turn_id=handle.turn_id,
                payload={
                    "status": "failed",
                    "answer_path": None,
                    "answer_sha256": None,
                    "duration_seconds": duration_seconds,
                },
            ),
            integrity="diagnostic",
        )
        _append_jsonl_fsync(self._workspace.answers_path, {"question_id": handle.turn_id, "answer_output": answer})
        self._remove_active_turn()
        return FinalizedTurn(
            turn_id=handle.turn_id,
            status="failed",
            answer_output=answer,
            answer_path=None,
            audit_diagnostics=(),
            error=error,
        )

    def _audit_answer(
        self,
        claim_evidence_refs: tuple[str, ...],
        result_refs: tuple[str, ...],
    ) -> tuple[ReferenceDiagnostic, ...]:
        try:
            return self._audit_callback(claim_evidence_refs, result_refs)
        except Exception as exc:
            return (
                ReferenceDiagnostic(
                    category="answer_audit_failed",
                    severity="warning",
                    reference="",
                    message=f"answer audit failed: {type(exc).__name__}: {exc}",
                    impact="The submitted answer was accepted, but reference diagnostics may be incomplete.",
                    remediation="Inspect the answer draft and rerun the shared answer audit.",
                ),
            )

    def _record_audit_diagnostic(self, handle: ActiveTurnHandle, diagnostic: ReferenceDiagnostic) -> None:
        self._store.append(
            ContextEventDraft(
                event_type="audit.diagnostic.recorded",
                turn_id=handle.turn_id,
                payload={
                    "message": diagnostic.message,
                    "category": diagnostic.category,
                    "severity": diagnostic.severity,
                    "reference": diagnostic.reference,
                    "impact": diagnostic.impact,
                    "remediation": diagnostic.remediation,
                },
            ),
            integrity="diagnostic",
        )

    def _clear_active_answer_draft(self) -> None:
        try:
            self._workspace.active_answer_draft_path.unlink()
        except FileNotFoundError:
            return

    def _remove_active_turn(self) -> None:
        try:
            self._workspace.active_turn_path.unlink()
        except FileNotFoundError:
            return


def _load_answer_draft(raw_draft: bytes) -> Mapping[str, Any]:
    try:
        draft = json.loads(raw_draft.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnswerDraftError("grid_submit_answer draft is not valid JSON") from exc
    if not isinstance(draft, Mapping):
        raise AnswerDraftError("grid_submit_answer draft must be a JSON object")
    return draft


def _require_current_turn_binding(draft: Mapping[str, Any], handle: ActiveTurnHandle) -> None:
    if draft.get("turn_id") != handle.turn_id or draft.get("turn_nonce") != handle.turn_nonce:
        raise StaleAnswerDraftError("grid_submit_answer draft is bound to a different turn")


def _require_non_empty_string(draft: Mapping[str, Any], key: str) -> str:
    value = draft.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AnswerDraftError(f"grid_submit_answer draft must include {key}")
    return value


def _require_string_list(draft: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = draft.get(key)
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(item, str) for item in value)
    ):
        raise AnswerDraftError(f"grid_submit_answer draft must include {key}")
    return tuple(value)


def _write_audit(path: Path, diagnostics: tuple[ReferenceDiagnostic, ...]) -> None:
    _write_json_atomic(
        path,
        {
            "diagnostics": [
                {
                    "category": diagnostic.category,
                    "severity": diagnostic.severity,
                    "reference": diagnostic.reference,
                    "message": diagnostic.message,
                    "impact": diagnostic.impact,
                    "remediation": diagnostic.remediation,
                }
                for diagnostic in diagnostics
            ]
        },
    )


def _append_jsonl_fsync(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    _write_bytes_atomic(path, encoded)
    return encoded


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _limitation_ref(turn_id: str, error: str) -> str:
    return "limitation:sha256:" + _sha256_text(f"{turn_id}\n{error}")


__all__ = [
    "ActiveTurnHandle",
    "AnswerDraftError",
    "FinalizedTurn",
    "StaleAnswerDraftError",
    "TurnController",
]
