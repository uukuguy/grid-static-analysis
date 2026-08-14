from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from grid_agent.trajectory.api.catalog import RunNotFoundError, TrajectoryRunCatalog
from grid_agent.trajectory.projection_models import ProjectedRun


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_native_run(root: Path) -> Path:
    write_json(
        root / "manifest.json",
        {
            "analysis_id": root.name,
            "status": "completed",
            "started_at": "2026-08-14T08:18:22Z",
        },
    )
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "events/run-events.jsonl").write_text("{}\n", encoding="utf-8")
    return root


def write_v02_run(root: Path) -> Path:
    write_json(root / "manifest.json", {"analysis_id": root.name, "total_turns": 2})
    return root


class FakeProjectionService:
    def __init__(self) -> None:
        self.opened: list[Path] = []

    def open_run(self, run_root: Path) -> ProjectedRun:
        self.opened.append(run_root)
        return cast(
            ProjectedRun, SimpleNamespace(agent=SimpleNamespace(turns=(object(), object())))
        )


def fake_projection_service() -> FakeProjectionService:
    return FakeProjectionService()


def test_catalog_discovers_native_and_v02_runs_by_manifest(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_native_run(runs / "analysis-native")
    write_v02_run(runs / "analysis-legacy")
    (runs / "not-a-run").mkdir(parents=True)
    catalog = TrajectoryRunCatalog(
        runs, tmp_path / ".grid-agent/trajectory-cache", fake_projection_service()
    )

    summaries = catalog.list_runs()

    assert [(item.analysis_id, item.source_kind) for item in summaries] == [
        ("analysis-native", "native"),
        ("analysis-legacy", "legacy-v0.2"),
    ]
    assert summaries[0].turn_count == 2


def test_catalog_rejects_manifest_id_directory_mismatch(tmp_path: Path) -> None:
    root = write_native_run(tmp_path / "runs/analysis-safe")
    write_json(root / "manifest.json", {"analysis_id": "../escape", "status": "completed"})
    catalog = TrajectoryRunCatalog(tmp_path / "runs", tmp_path / "cache", fake_projection_service())

    assert catalog.list_runs() == ()
    with pytest.raises(RunNotFoundError):
        catalog.open("../escape")


def test_catalog_ignores_symlinked_run_directory(tmp_path: Path) -> None:
    outside = write_native_run(tmp_path / "outside/analysis-outside")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "analysis-link").symlink_to(outside, target_is_directory=True)

    assert (
        TrajectoryRunCatalog(runs, tmp_path / "cache", fake_projection_service()).list_runs()
        == ()
    )


def test_catalog_rejects_symlinked_manifest_or_event_stream(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    outside = write_native_run(tmp_path / "outside/analysis-safe")
    run = runs / "analysis-safe"
    run.mkdir(parents=True)
    (run / "manifest.json").symlink_to(outside / "manifest.json")

    assert TrajectoryRunCatalog(runs, tmp_path / "cache", fake_projection_service()).list_runs() == ()


def test_catalog_reports_corrupt_only_after_manifest_identity_is_safe(tmp_path: Path) -> None:
    root = write_native_run(tmp_path / "runs/analysis-safe")
    (root / "events/run-events.jsonl").write_text("not-json\n", encoding="utf-8")

    summary = TrajectoryRunCatalog(
        tmp_path / "runs", tmp_path / "cache", fake_projection_service()
    ).list_runs()[0]

    assert summary.status == "corrupt"
    assert summary.diagnostic is not None
    assert str(tmp_path) not in summary.diagnostic
