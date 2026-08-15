"""Single read-only entry point for native and imported trajectory projections."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from collections.abc import Sequence
from typing import cast

from grid_agent.trajectory.agent_projection import project_agent
from grid_agent.trajectory.artifact_projection import project_artifacts
from grid_agent.trajectory.business_projection import project_business
from grid_agent.trajectory.context_projection import project_context
from grid_agent.trajectory.legacy_v02 import LegacyV02Importer
from grid_agent.trajectory.artifacts import ArtifactPointer
from grid_agent.trajectory.materialize import ProjectionMaterializer
from grid_agent.trajectory.projection_models import ProjectedRun, ProjectionDiagnostic
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.replay import ReplayEventLike


class _HistoricalArtifacts:
    """Only admits v0.2 result/evidence references backed by their named file."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root

    def verify(self, reference: str) -> SimpleNamespace:
        if not (reference.startswith("result:sha256:") or reference.startswith("evidence:sha256:")):
            raise RuntimeError("historical artifact reference is unavailable")
        digest = reference.rsplit(":", 1)[-1]
        matches = tuple(self.run_root.glob("evidence/**/*.json"))
        for path in matches:
            # v0.2 references name a content-addressed domain record; the JSON
            # wrapper itself is not necessarily hashed as the reference payload.
            if digest in path.name:
                return SimpleNamespace(authority="gridctl", integrity="verified")
        raise RuntimeError("historical artifact digest is unavailable")

    def verify_reference(self, reference: str) -> object:
        raise RuntimeError("v0.2 references are not native artifact pointers")


class _NativeArtifacts:
    """Verify native artifact pointers by their digest, never legacy filenames."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root

    def verify_reference(self, reference: str) -> ArtifactPointer:
        if not reference.startswith("artifact:sha256:"):
            raise RuntimeError("native artifact reference is unavailable")
        digest = reference.rsplit(":", 1)[-1]
        for path in sorted(self.run_root.glob("requests/**/*.json")) + sorted(self.run_root.glob("turns/**/*.json")) + sorted(self.run_root.glob("context/views/**/*.json")):
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                continue
            relative = path.relative_to(self.run_root).as_posix()
            kind = "request-input" if relative.startswith("requests/") and path.name == "input.json" else "model-response" if relative.startswith("requests/") else "answer" if relative.startswith("turns/") else "context-view"
            return ArtifactPointer(ref=reference, kind=kind, relative_path=relative, sha256=digest, size_bytes=path.stat().st_size)
        raise RuntimeError("native artifact digest is unavailable")

    def verify(self, reference: str | ArtifactPointer) -> Path:
        pointer = self.verify_reference(reference) if isinstance(reference, str) else reference
        if not isinstance(pointer, ArtifactPointer):
            raise RuntimeError("native artifact pointer is unavailable")
        if pointer.ref != f"artifact:sha256:{pointer.sha256}":
            raise RuntimeError("native artifact pointer has an invalid reference")
        path = self.run_root / pointer.relative_path
        try:
            path.resolve(strict=True).relative_to(self.run_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise RuntimeError("native artifact pointer escapes the run root") from exc
        value = path.read_bytes()
        if len(value) != pointer.size_bytes:
            raise RuntimeError("native artifact size does not match its pointer")
        if hashlib.sha256(value).hexdigest() != pointer.sha256:
            raise RuntimeError("native artifact digest does not match its pointer")
        return path


class ProjectionService:
    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)

    def open_run(self, run_root: Path) -> ProjectedRun:
        run_root = Path(run_root)
        native_path = run_root / "events/run-events.jsonl"
        if native_path.is_file():
            prefix = RunEventReader(native_path).read_prefix()
            events = prefix.events
            source_fingerprint = hashlib.sha256(native_path.read_bytes()).hexdigest()
            extra = () if prefix.failure is None else (ProjectionDiagnostic(id="native-replay-failure", source_sequences=(max(1, len(events)),), rule_id="native-prefix-validation/v1", severity="error", code=prefix.failure.code, message=prefix.failure.message),)
            artifacts = _NativeArtifacts(run_root)
        else:
            imported = LegacyV02Importer(run_root).import_run()
            events, source_fingerprint = imported.events, imported.source_fingerprint
            extra = tuple(ProjectionDiagnostic(id=f"legacy:{item.code}", source_sequences=(1,), rule_id="legacy-import/v1", severity="warning", code=item.code, message=item.message) for item in imported.diagnostics)
            artifacts = _HistoricalArtifacts(run_root)
        replay_events = cast(Sequence[ReplayEventLike], events)
        projected = ProjectedRun(analysis_id=events[0].analysis_id if events else run_root.name, source_fingerprint=source_fingerprint, agent=project_agent(replay_events), business=project_business(replay_events, artifacts), context=project_context(replay_events, artifacts), artifacts=project_artifacts(replay_events, artifacts), diagnostics=extra)
        ProjectionMaterializer(self.cache_root).write(projected, source_fingerprint)
        return projected


__all__ = ["ProjectionService"]
