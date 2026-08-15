from __future__ import annotations

import shutil

import pytest

from grid_agent.trajectory.materialize import ProjectionMaterializer
from grid_agent.trajectory.projection_models import AgentTrajectory, ArtifactIndex, BusinessTrajectory, ContextTimeline, ProjectedRun


def test_materialized_cache_rebuild_is_byte_identical(tmp_path) -> None:
    projected = ProjectedRun(analysis_id="analysis-1", source_fingerprint="source-a", agent=AgentTrajectory(analysis_id="analysis-1"), business=BusinessTrajectory(analysis_id="analysis-1"), context=ContextTimeline(analysis_id="analysis-1"), artifacts=ArtifactIndex(analysis_id="analysis-1"))
    materializer = ProjectionMaterializer(tmp_path / ".grid-agent" / "trajectory-cache")
    first = materializer.write(projected, "source-a")
    first_bytes = {path.name: path.read_bytes() for path in first.all_paths}
    shutil.rmtree(first.cache_root)
    second = materializer.write(projected, "source-a")
    assert {path.name: path.read_bytes() for path in second.all_paths} == first_bytes
    assert materializer.load_if_current("analysis-1", "source-a") == projected


@pytest.mark.parametrize("unsafe", ["", ".", "..", "/tmp/key", "a/b", "a\\b"])
def test_materializer_rejects_unsafe_cache_path_segments(tmp_path, unsafe: str) -> None:
    materializer = ProjectionMaterializer(tmp_path / ".grid-agent" / "trajectory-cache")
    projected = ProjectedRun(analysis_id="analysis-1", source_fingerprint="source-a", agent=AgentTrajectory(analysis_id="analysis-1"), business=BusinessTrajectory(analysis_id="analysis-1"), context=ContextTimeline(analysis_id="analysis-1"), artifacts=ArtifactIndex(analysis_id="analysis-1"))

    with pytest.raises(ValueError, match="cache path segment"):
        materializer.write(projected.model_copy(update={"analysis_id": unsafe}), "source-a")

    with pytest.raises(ValueError, match="cache path segment"):
        materializer.load_if_current("analysis-1", unsafe)
