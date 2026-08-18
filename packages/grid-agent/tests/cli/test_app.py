from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from grid_agent.analysis.runner import AnalysisOutcome
from grid_agent.cli.app import app
from grid_agent.contracts import AnswerEnvelope


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def cli_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, Path]:
    instructions = tmp_path / "task.md.txt"
    instructions.write_text("运行交流潮流\n筛选负载率最高的5条线路\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return CliRunner(), instructions


def _fake_execute_analysis(*, instructions: Path, artifact_root: Path | None, provider: str | None, model: str | None) -> AnalysisOutcome:
    project_root = Path.cwd()
    root = artifact_root or project_root / "runs"
    analysis_id = "analysis-test"
    analysis_root = root / analysis_id
    (analysis_root / "input").mkdir(parents=True)
    (analysis_root / "output").mkdir()
    (analysis_root / "context").mkdir()
    (analysis_root / "input/instructions.md.txt").write_text(instructions.read_text(encoding="utf-8"), encoding="utf-8")
    (analysis_root / "output/answers.jsonl").write_text("", encoding="utf-8")
    (analysis_root / "context/analysis-context.json").write_text("{}", encoding="utf-8")
    (analysis_root / "report.md").write_text("# report\n", encoding="utf-8")
    return AnalysisOutcome(
        analysis_id=analysis_id,
        status="completed",
        report_path=analysis_root / "report.md",
        completed_turns=2,
        total_turns=2,
    )


def _fail_if_called(*_args: Any, **_kwargs: Any) -> subprocess.Popen[str]:
    raise AssertionError("report must not launch child grid-agent run subprocesses")


def test_analysis_cli_emits_one_envelope_and_uses_self_contained_paths(
    cli_harness: tuple[CliRunner, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, instructions = cli_harness
    monkeypatch.setattr("grid_agent.cli.app._execute_analysis", _fake_execute_analysis)

    result = runner.invoke(app, ["analysis", "--instructions", str(instructions)])

    assert result.exit_code == 0
    assert len(result.stdout.splitlines()) == 1
    envelope = AnswerEnvelope.model_validate_json(result.stdout)
    assert set(json.loads(result.stdout)) == {"question_id", "answer_output"}
    assert "trajectory" not in result.stdout
    analysis_root = instructions.parent / "runs" / envelope.question_id
    assert envelope.answer_output == f"runs/{envelope.question_id}/report.md"
    assert (analysis_root / "input/instructions.md.txt").is_file()
    assert (analysis_root / "output/answers.jsonl").is_file()
    assert (analysis_root / "context/analysis-context.json").is_file()


def test_failed_analysis_envelope_points_to_partial_report(
    cli_harness: tuple[CliRunner, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, instructions = cli_harness

    def failed_analysis(**kwargs: Any) -> AnalysisOutcome:
        completed = _fake_execute_analysis(**kwargs)
        return AnalysisOutcome(
            analysis_id=completed.analysis_id,
            status="failed",
            report_path=completed.report_path,
            completed_turns=4,
            total_turns=9,
            error="PiProtocolError: Pi provider failure: terminated",
        )

    monkeypatch.setattr("grid_agent.cli.app._execute_analysis", failed_analysis)

    result = runner.invoke(app, ["analysis", "--instructions", str(instructions)])

    assert result.exit_code == 1
    envelope = AnswerEnvelope.model_validate_json(result.stdout)
    assert envelope.answer_output == "分析未完成；部分报告已保存：runs/analysis-test/report.md"
    assert "execution limitation" not in result.stdout


def test_report_command_delegates_to_analysis_without_child_run(
    cli_harness: tuple[CliRunner, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, instructions = cli_harness
    monkeypatch.setattr("grid_agent.cli.app._execute_analysis", _fake_execute_analysis)
    monkeypatch.setattr(subprocess, "Popen", _fail_if_called)

    result = runner.invoke(app, ["report", "--questions", str(instructions)])

    assert result.exit_code == 0
    assert AnswerEnvelope.model_validate_json(result.stdout).question_id.startswith("analysis-")


def test_trajectory_serve_delegates_without_answer_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("grid_agent.cli.app.serve_trajectory", lambda **kwargs: observed.update(kwargs))

    result = CliRunner().invoke(app, ["trajectory", "serve", "--port", "9000"])

    assert result.exit_code == 0
    assert result.stdout == ""
    assert observed["port"] == 9000
    assert observed["host"] == "127.0.0.1"
    assert observed["runs_root"] == Path("runs")


def test_trajectory_serve_reports_startup_errors_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "grid_agent.cli.app.serve_trajectory",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("missing assets")),
    )

    result = CliRunner().invoke(app, ["trajectory", "serve"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "grid-agent trajectory error: missing assets" in result.stderr
