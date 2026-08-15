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
from grid_agent.analysis.integrity import ContentReferenceVerifier
from grid_agent.trajectory.artifacts import ArtifactIntegrityError, ArtifactPointer, ImmutableArtifactRegistry
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
        if reference.startswith("artifact:sha256:"):
            for kind, identity, path in self._artifact_ref_candidates():
                pointer = self._register_existing(kind, identity, path)
                if pointer is not None and pointer.ref == reference:
                    return pointer
            raise RuntimeError("native artifact digest is unavailable")
        if reference.startswith("result:sha256:"):
            verified = ContentReferenceVerifier(self.run_root).verify_result(reference)
            pointer = self._register_existing("result", reference, verified.path)
            if pointer is not None:
                return ArtifactPointer(
                    ref=reference,
                    kind=pointer.kind,
                    relative_path=pointer.relative_path,
                    sha256=pointer.sha256,
                    size_bytes=pointer.size_bytes,
                )
            raise RuntimeError("native result artifact is unavailable")
        if reference.startswith("evidence:sha256:"):
            verified = ContentReferenceVerifier(self.run_root).verify_evidence(reference)
            pointer = self._register_existing("evidence", reference, verified.path)
            if pointer is not None:
                return ArtifactPointer(
                    ref=reference,
                    kind=pointer.kind,
                    relative_path=pointer.relative_path,
                    sha256=pointer.sha256,
                    size_bytes=pointer.size_bytes,
                )
            raise RuntimeError("native evidence artifact is unavailable")
        raise RuntimeError("native artifact digest is unavailable")

    def verify(self, reference: str | ArtifactPointer) -> Path | SimpleNamespace:
        if isinstance(reference, str) and reference.startswith(("result:sha256:", "evidence:sha256:")):
            self.verify_reference(reference)
            return SimpleNamespace(authority="gridctl", integrity="verified")
        pointer = self.verify_reference(reference) if isinstance(reference, str) else reference
        if not isinstance(pointer, ArtifactPointer):
            raise RuntimeError("native artifact pointer is unavailable")
        if pointer.ref.startswith(("result:sha256:", "evidence:sha256:")):
            self.verify_reference(pointer.ref)
            return SimpleNamespace(authority="gridctl", integrity="verified")
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

    def _register_existing(
        self, kind: str, identity: str, path: Path
    ) -> ArtifactPointer | None:
        try:
            return ImmutableArtifactRegistry(self.run_root).register_existing(kind, identity, path)
        except (ArtifactIntegrityError, OSError):
            return None

    def _artifact_ref_candidates(self) -> tuple[tuple[str, str, Path], ...]:
        candidates: list[tuple[str, str, Path]] = []
        for path in sorted(self.run_root.glob("requests/*/input.json")):
            candidates.append(("request-input", path.parent.name, path))
        for path in sorted(self.run_root.glob("requests/*/response.json")):
            candidates.append(("model-response", path.parent.name, path))
        for path in sorted(self.run_root.glob("turns/*/answer.json")):
            candidates.append(("answer", path.parent.name, path))
        for path in sorted(self.run_root.glob("context/views/*/view.json")):
            candidates.append(("context-view", path.parent.name, path))
        for path in sorted(self.run_root.glob("tool-results/*/*.json")):
            candidates.append(("tool-result", f"{path.parent.name}:{path.stem}", path))
        return tuple(candidates)


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
