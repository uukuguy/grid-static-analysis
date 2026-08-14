import json
from hashlib import sha256
from pathlib import Path

import pytest

from grid_agent.analysis.workspace import AnalysisWorkspace
from grid_agent.trajectory.events import RunEvent


def test_analysis_workspace_creates_one_complete_run_tree(tmp_path: Path) -> None:
    source = tmp_path / "task.md.txt"
    source.write_text("第一条指令\n第二条指令\n", encoding="utf-8")
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")

    copied = workspace.copy_instructions(source)

    assert workspace.root_path == tmp_path / "runs/analysis-test"
    assert workspace.copied_instructions_path.read_bytes() == source.read_bytes()
    assert copied.sha256 == sha256(source.read_bytes()).hexdigest()
    assert copied.instruction_count == 2
    assert workspace.report_path == workspace.root_path / "report.md"
    assert workspace.answers_path == workspace.root_path / "output/answers.jsonl"
    assert workspace.context_snapshot_path == workspace.root_path / "context/analysis-context.json"
    assert workspace.context_events_path == workspace.root_path / "context/context-events.jsonl"
    for path in (workspace.turns_path, workspace.evidence_path, workspace.results_path, workspace.pi_path):
        assert path.is_dir()


def test_copy_instructions_rejects_a_second_different_source(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("一\n", encoding="utf-8")
    second.write_text("二\n", encoding="utf-8")
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    workspace.copy_instructions(first)

    with pytest.raises(RuntimeError, match="already contains copied instructions"):
        workspace.copy_instructions(second)


def test_analysis_workspace_exposes_native_trajectory_paths(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")

    assert workspace.events_path == workspace.root_path / "events/run-events.jsonl"
    assert workspace.requests_path == workspace.root_path / "requests"
    assert workspace.agent_projection_path == workspace.root_path / "projections/agent-trajectory.json"
    assert workspace.business_projection_path == workspace.root_path / "projections/business-trajectory.json"
    assert workspace.context_timeline_path == workspace.root_path / "projections/context-timeline.json"
    assert workspace.artifact_index_path == workspace.root_path / "projections/artifact-index.json"
    assert workspace.requests_path.is_dir()
    assert workspace.projections_path.is_dir()


def test_checked_in_trajectory_schema_matches_model() -> None:
    root = Path(__file__).resolve().parents[4]
    actual = json.loads((root / "schemas/grid-run-event-v1.schema.json").read_text(encoding="utf-8"))

    assert actual == RunEvent.model_json_schema()
