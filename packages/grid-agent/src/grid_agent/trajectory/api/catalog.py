"""Manifest-bound discovery for read-only trajectory runs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from grid_agent.trajectory.api.models import AnalysisManifest, LegacyV02Manifest, RunSummary
from grid_agent.trajectory.projection_models import ProjectedRun
from grid_agent.trajectory.reader import RunEventReader


ANALYSIS_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class ProjectionOpener(Protocol):
    def open_run(self, run_root: Path) -> ProjectedRun: ...


class RunNotFoundError(LookupError):
    """The requested run is not a discovered, safe run."""

    def __init__(self, analysis_id: str) -> None:
        super().__init__(f"trajectory run not found: {analysis_id}")


class TrajectoryRunCatalog:
    """Discover immediate child run directories without accepting request paths."""

    def __init__(
        self, runs_root: Path, cache_root: Path, projection_service: ProjectionOpener
    ) -> None:
        self.runs_root = Path(runs_root)
        self.cache_root = Path(cache_root)
        self.projection_service = projection_service

    def list_runs(self) -> tuple[RunSummary, ...]:
        try:
            root = self.runs_root.resolve(strict=True)
        except OSError:
            return ()
        if not root.is_dir():
            return ()

        summaries: list[RunSummary] = []
        for candidate in sorted(root.iterdir()):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                run_root = candidate.resolve(strict=True)
                if run_root.parent != root:
                    continue
                manifest, source_kind = self._load_manifest(run_root, candidate.name)
                summaries.append(self._summary(run_root, manifest, source_kind))
            except (OSError, ValidationError, ValueError):
                continue
        return tuple(
            sorted(
                summaries,
                key=lambda item: (item.started_at or "", item.analysis_id),
                reverse=True,
            )
        )

    def open(self, analysis_id: str) -> ProjectedRun:
        if not ANALYSIS_ID.fullmatch(analysis_id):
            raise RunNotFoundError(analysis_id)
        try:
            root = self.runs_root.resolve(strict=True)
            run_root = root / analysis_id
            if run_root.is_symlink() or not run_root.is_dir():
                raise RunNotFoundError(analysis_id)
            resolved = run_root.resolve(strict=True)
            if resolved.parent != root:
                raise RunNotFoundError(analysis_id)
            self._load_manifest(resolved, analysis_id)
        except (OSError, ValidationError, ValueError) as exc:
            raise RunNotFoundError(analysis_id) from exc
        return self.projection_service.open_run(resolved)

    @staticmethod
    def _load_manifest(run_root: Path, directory_id: str) -> tuple[AnalysisManifest | LegacyV02Manifest, str]:
        manifest_path = _safe_run_file(run_root, "manifest.json")
        raw = manifest_path.read_text(encoding="utf-8")
        try:
            native = AnalysisManifest.model_validate_json(raw)
        except ValidationError:
            native = None
        if native is not None:
            if native.analysis_id != directory_id or not ANALYSIS_ID.fullmatch(native.analysis_id):
                raise ValueError("manifest identity does not match run directory")
            events_path = run_root / native.events_path
            if native.schema_version == "grid-agent-analysis-manifest/1.0" or events_path.is_file():
                if native.events_path != "events/run-events.jsonl":
                    raise ValueError("native manifest does not name the native event stream")
                events_path = _safe_run_file(run_root, native.events_path)
                return native, "native"

        legacy = LegacyV02Manifest.model_validate_json(raw)
        if legacy.analysis_id != directory_id or not ANALYSIS_ID.fullmatch(legacy.analysis_id):
            raise ValueError("manifest identity does not match run directory")
        return legacy, "legacy-v0.2"

    def _summary(
        self,
        run_root: Path,
        manifest: AnalysisManifest | LegacyV02Manifest,
        source_kind: str,
    ) -> RunSummary:
        diagnostic: str | None = None
        status = manifest.status or "unavailable"
        last_sequence: int | None = None
        replay_trusted_through: int | None = None
        if source_kind == "native":
            prefix = RunEventReader(run_root / "events/run-events.jsonl").read_prefix()
            last_sequence = prefix.events[-1].sequence if prefix.events else 0
            replay_trusted_through = last_sequence
            if prefix.failure is not None:
                status = "corrupt"
                diagnostic = f"native trajectory is corrupt ({prefix.failure.code})"
        try:
            projected = self.projection_service.open_run(run_root)
            turn_count = len(projected.agent.turns)
        except Exception:
            # A manifest-identified run remains listable, but never divulges a
            # path or importer exception in its operator-facing diagnostic.
            turn_count = manifest.total_turns or 0
            status = "corrupt"
            diagnostic = diagnostic or "trajectory projection is unavailable"
        return RunSummary(
            analysis_id=manifest.analysis_id,
            status=status,
            source_kind=source_kind,
            started_at=manifest.started_at,
            turn_count=turn_count,
            last_sequence=last_sequence,
            replay_trusted_through=replay_trusted_through,
            diagnostic=diagnostic,
        )


def _safe_run_file(run_root: Path, relative_path: str) -> Path:
    """Return a fixed regular run file only when every resolution stays local."""
    path = run_root / relative_path
    if path.is_symlink() or not path.is_file():
        raise ValueError("required run file is unavailable")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(run_root):
        raise ValueError("required run file escapes its run directory")
    return resolved


__all__ = ["ANALYSIS_ID", "RunNotFoundError", "TrajectoryRunCatalog"]
