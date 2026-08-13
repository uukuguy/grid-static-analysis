from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from grid_agent.analysis.integrity import SimulatorIntegrityError
from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.report import write_analysis_report_checkpoint
from grid_agent.analysis.store import AnalysisContextStore, ContextStoreError
from grid_agent.analysis.turns import ActiveTurnHandle, FinalizedTurn, TurnController
from grid_agent.analysis.view import materialize_context_view
from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.runtime.rpc import PiProtocolError, SemanticEventCallback
from grid_agent.observability.trace import JsonlTraceWriter


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    analysis_id: str
    instructions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    analysis_id: str
    status: Literal["completed", "failed"]
    report_path: Path
    completed_turns: int
    total_turns: int
    error: str | None = None


ManifestStatus = Literal["completed", "failed"]


class PiSession(Protocol):
    def start(self) -> None: ...

    def prompt_and_wait(
        self,
        question: str,
        *,
        on_event: ProgressCallback | None = None,
        on_semantic_event: SemanticEventCallback | None = None,
        on_heartbeat: Callable[[], None] | None = None,
        heartbeat_seconds: float = 10.0,
        require_answer_text: bool = True,
    ) -> str: ...

    def stop(self) -> None: ...


class ContextProjector(Protocol):
    def observe(self, event: Mapping[str, Any], *, turn_id: str, trace_sequence: int | None = None) -> None: ...


ProgressCallback = Callable[[dict[str, Any]], None]


class AnalysisRunner:
    """Run ordered analysis instructions inside one Pi process."""

    def __init__(
        self,
        *,
        workspace: AnalysisWorkspace,
        store: AnalysisContextStore,
        turn_controller: TurnController,
        pi_client: PiSession,
        projector: ContextProjector,
        environment: Mapping[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
        trace: JsonlTraceWriter | None = None,
    ) -> None:
        self._workspace = workspace
        self._store = store
        self._turns = turn_controller
        self._pi = pi_client
        self._projector = projector
        self._environment = dict(environment or {})
        self._progress_callback = progress_callback
        self._trace = trace
        self._last_context_revision: int | None = None

    def run(self, request: AnalysisRequest) -> AnalysisOutcome:
        if request.analysis_id != self._workspace.analysis_id or request.analysis_id != self._store.snapshot.analysis_id:
            raise ValueError("analysis request id does not match workspace context")

        try:
            try:
                # Pi loads the extension before the first prompt; its configured
                # context-view path must therefore already exist.
                self._materialize_context_view()
                self._pi.start()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._fail_analysis(error, total_turns=len(request.instructions))
                return self._outcome(request, "failed", error)

            for ordinal, instruction in enumerate(request.instructions, start=1):
                try:
                    handle = self._turns.start(ordinal, instruction)
                except ContextStoreError as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    self._fail_analysis(error, total_turns=len(request.instructions))
                    return self._outcome(request, "failed", error)
                try:
                    self._materialize_context_view()
                    self._pi.prompt_and_wait(
                        self._prompt_for(instruction),
                        on_event=self._progress_callback,
                        on_semantic_event=lambda event, sequence, turn_id=handle.turn_id: self._observe_semantic_event(
                            event,
                            turn_id=turn_id,
                            trace_sequence=sequence,
                        ),
                        require_answer_text=False,
                    )
                    finalized = self._finalize_turn(handle)
                except PiProtocolError as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    finalized = self._fail_turn_if_active(handle, error)
                    self._checkpoint_after_turn(finalized)
                    self._fail_analysis(error, total_turns=len(request.instructions))
                    return self._outcome(request, "failed", error)
                except SimulatorIntegrityError as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    finalized = self._fail_turn_if_active(handle, error)
                    self._checkpoint_after_turn(finalized)
                    self._fail_analysis(error, total_turns=len(request.instructions))
                    return self._outcome(request, "failed", error)
                except ContextStoreError as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    finalized = self._fail_turn_if_active(handle, error)
                    self._checkpoint_after_turn(finalized)
                    self._fail_analysis(error, total_turns=len(request.instructions))
                    return self._outcome(request, "failed", error)

                self._checkpoint_after_turn(finalized)

            try:
                self._verify_running_state_before_completion()
                self._store.append(
                    ContextEventDraft(
                        event_type="analysis.completed",
                        payload={
                            "completed_turns": len(self._store.snapshot.turns),
                            "total_turns": len(request.instructions),
                        },
                    )
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._fail_analysis(error, total_turns=len(request.instructions))
                return self._outcome(request, "failed", error)

            self._write_final_artifacts(status="completed", error=None, total_turns=len(request.instructions))
            return self._outcome(request, "completed", None)
        finally:
            self._pi.stop()

    def _finalize_turn(self, handle: ActiveTurnHandle) -> FinalizedTurn:
        return self._turns.finalize(handle, duration_seconds=max(0.0, time.monotonic() - handle.started_monotonic))

    def _fail_turn_if_active(self, handle: ActiveTurnHandle, error: str) -> FinalizedTurn:
        if self._store.snapshot.current_turn is None:
            return FinalizedTurn(
                turn_id=handle.turn_id,
                status="failed",
                answer_output=f"执行限制 / execution limitation: {error}",
                answer_path=None,
                audit_diagnostics=(),
                error=error,
            )
        try:
            return self._turns.fail(
                handle,
                error=error,
                duration_seconds=max(0.0, time.monotonic() - handle.started_monotonic),
            )
        except ContextStoreError:
            return FinalizedTurn(
                turn_id=handle.turn_id,
                status="failed",
                answer_output=f"执行限制 / execution limitation: {error}",
                answer_path=None,
                audit_diagnostics=(),
                error=error,
            )

    def _checkpoint_after_turn(self, _finalized: FinalizedTurn) -> None:
        if self._store.snapshot.current_turn is not None:
            return
        self._materialize_context_view()
        write_analysis_report_checkpoint(
            context=self._store.snapshot,
            workspace=self._workspace,
            environment=self._environment,
        )

    def _observe_semantic_event(
        self,
        event: Mapping[str, Any],
        *,
        turn_id: str,
        trace_sequence: int,
    ) -> None:
        """Keep context projection diagnostic-only for the live Pi session.

        The Pi process is the answer-producing path.  Projection enriches the
        auditable report, but a rejected or unavailable projection must never
        interrupt an already-running tool conversation before it can submit its
        answer.
        """
        try:
            self._projector.observe(event, turn_id=turn_id, trace_sequence=trace_sequence)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if self._trace is not None:
                self._trace.append(
                    "analysis_context.projection_failed",
                    {"turn_id": turn_id, "trace_sequence": trace_sequence, "error": message},
                )
            if self._store.snapshot.current_turn is None:
                return
            try:
                self._store.append(
                    ContextEventDraft(
                        event_type="limitation.recorded",
                        turn_id=turn_id,
                        payload={
                            "limitation_ref": f"context-projection:{turn_id}:{trace_sequence}",
                            "message": f"上下文审计诊断：{message}",
                            "refs": [],
                        },
                    ),
                    integrity="diagnostic",
                )
            except ContextStoreError:
                # The trace above remains the diagnostic record when the
                # optional context store itself is unavailable.
                pass

    def _verify_running_state_before_completion(self) -> None:
        self._store.verify_materialized_snapshot()
        replayed = AnalysisContextStore.replay(self._workspace.context_events_path)
        if replayed != self._store.snapshot:
            raise ContextStoreError("replayed context does not match in-memory snapshot before completion")

    def _fail_analysis(self, error: str, *, total_turns: int) -> None:
        if self._store.snapshot.status not in {"completed", "failed"} and self._store.snapshot.current_turn is None:
            try:
                self._store.append(
                    ContextEventDraft(
                        event_type="analysis.failed",
                        payload={"error": error},
                    ),
                    integrity="diagnostic",
                )
            except ContextStoreError:
                pass
        self._write_final_artifacts(status="failed", error=error, total_turns=total_turns)

    def _write_final_artifacts(
        self,
        *,
        status: ManifestStatus,
        error: str | None,
        total_turns: int,
    ) -> None:
        context_available = self._store.snapshot.status in {"completed", "failed"} and self._store.snapshot.current_turn is None
        if context_available:
            self._materialize_context_view()
            write_analysis_report_checkpoint(
                context=self._store.snapshot,
                workspace=self._workspace,
                environment=self._environment,
            )
        manifest: dict[str, Any] = {
            "schema_version": "grid-agent-analysis-manifest/1.0",
            "analysis_id": self._workspace.analysis_id,
            "status": status,
            "completed_turns": len(self._store.snapshot.turns),
            "total_turns": total_turns,
            "report_path": str(self._workspace.report_path.relative_to(self._workspace.root_path)) if context_available else None,
            "context_path": str(self._workspace.context_snapshot_path.relative_to(self._workspace.root_path)),
            "context_events_path": str(self._workspace.context_events_path.relative_to(self._workspace.root_path)),
            "context_available": context_available,
        }
        if error is not None:
            manifest["error"] = error
        _write_json_atomic(self._workspace.manifest_path, manifest)

    def _materialize_context_view(self) -> None:
        materialize_context_view(self._store.snapshot, self._workspace.context_view_path)
        if self._trace is None:
            return
        revision = self._store.snapshot.revision
        state_hash = self._store.snapshot.state_hash
        if revision != self._last_context_revision:
            self._trace.append("analysis_context.changed", {"revision": revision, "state_hash": state_hash})
        self._trace.append("analysis_context.injected", {"revision": revision, "state_hash": state_hash, "path": str(self._workspace.context_view_path.relative_to(self._workspace.root_path))})
        self._last_context_revision = revision

    def _prompt_for(self, instruction: str) -> str:
        context_view = self._workspace.context_view_path.read_text(encoding="utf-8")
        return (
            "你是 grid-agent 的连续静态分析执行器。"
            "必须只使用已注册的 grid tools 获取或复用仿真结论，并在完成本条指令时调用 grid_submit_answer。"
            "\n\n"
            "<analysis_context_view>\n"
            f"{context_view.rstrip()}\n"
            "</analysis_context_view>\n\n"
            "<instruction>\n"
            f"{instruction}\n"
            "</instruction>\n"
        )

    def _outcome(
        self,
        request: AnalysisRequest,
        status: Literal["completed", "failed"],
        error: str | None,
    ) -> AnalysisOutcome:
        return AnalysisOutcome(
            analysis_id=request.analysis_id,
            status=status,
            report_path=self._workspace.report_path,
            completed_turns=len(self._store.snapshot.turns),
            total_turns=len(request.instructions),
            error=error,
        )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
