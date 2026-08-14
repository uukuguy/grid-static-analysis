"""Disposable canonical JSON cache for projected trajectories."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.projection_models import ProjectedRun


PROJECTION_SCHEMA = "trajectory-projection/1.0"


@dataclass(frozen=True, slots=True)
class MaterializedPaths:
    cache_root: Path
    projected_run: Path
    agent: Path
    business: Path
    context: Path
    artifacts: Path

    @property
    def all_paths(self) -> tuple[Path, ...]:
        return (self.projected_run, self.agent, self.business, self.context, self.artifacts)


class ProjectionMaterializer:
    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)

    def _paths(self, analysis_id: str, fingerprint: str) -> MaterializedPaths:
        root = self.cache_root / analysis_id / fingerprint / PROJECTION_SCHEMA
        return MaterializedPaths(root, root / "projected-run.json", root / "agent.json", root / "business.json", root / "context.json", root / "artifacts.json")

    def write(self, projected_run: ProjectedRun, source_fingerprint: str) -> MaterializedPaths:
        if projected_run.source_fingerprint != source_fingerprint:
            raise ValueError("projected run fingerprint does not match cache key")
        paths = self._paths(projected_run.analysis_id, source_fingerprint)
        payloads = {
            paths.projected_run: projected_run.model_dump(mode="json"),
            paths.agent: projected_run.agent.model_dump(mode="json"),
            paths.business: projected_run.business.model_dump(mode="json"),
            paths.context: projected_run.context.model_dump(mode="json"),
            paths.artifacts: projected_run.artifacts.model_dump(mode="json"),
        }
        paths.cache_root.mkdir(parents=True, exist_ok=True)
        for path, value in payloads.items():
            _atomic_write(path, canonical_json_bytes(value))
        return paths

    def load_if_current(self, analysis_id: str, source_fingerprint: str) -> ProjectedRun | None:
        path = self._paths(analysis_id, source_fingerprint).projected_run
        try:
            projected = ProjectedRun.model_validate_json(path.read_bytes())
        except (OSError, ValueError):
            return None
        return projected if projected.source_fingerprint == source_fingerprint else None


def _atomic_write(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


__all__ = ["MaterializedPaths", "PROJECTION_SCHEMA", "ProjectionMaterializer"]
