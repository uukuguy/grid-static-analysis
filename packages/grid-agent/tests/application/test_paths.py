from pathlib import Path

from grid_agent.application.paths import ProjectPaths
from grid_agent.application.workspace import RunWorkspace


def test_project_paths_separate_internal_state_from_auditable_runs(tmp_path: Path) -> None:
    paths = ProjectPaths.from_root(tmp_path)

    assert paths.runs_dir == tmp_path / "runs"
    assert paths.internal_dir == tmp_path / ".grid-agent"
    assert paths.pi_runtime_dir == tmp_path / ".grid-agent/runtime/pi"
    assert paths.pi_agent_dir == tmp_path / ".grid-agent/auth/pi"
    assert paths.sessions_dir == tmp_path / ".grid-agent/sessions"
    assert paths.runtime_lock == tmp_path / "configs/runtime/pi-runtime.lock.json"


def test_run_workspace_uses_operator_visible_layout(tmp_path: Path) -> None:
    workspace = RunWorkspace.create(ProjectPaths.from_root(tmp_path).runs_dir, "q-test")

    assert workspace.root_path == tmp_path / "runs/q-test"
    assert workspace.tool_results_path == tmp_path / "runs/q-test/tool-results"
    assert workspace.evidence_path == tmp_path / "runs/q-test/evidence"
    assert workspace.answer_path == tmp_path / "runs/q-test/answer.json"
