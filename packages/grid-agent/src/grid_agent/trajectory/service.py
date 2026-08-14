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
