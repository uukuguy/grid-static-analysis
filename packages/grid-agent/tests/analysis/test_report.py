from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent, ContextEventDraft
from grid_agent.analysis.reducer import initial_context, reduce_context
from grid_agent.analysis.report import render_analysis_report, write_analysis_report_checkpoint
from grid_agent.analysis.workspace import AnalysisWorkspace


RESULT_REF = "result:sha256:" + "1" * 64
EVIDENCE_REF = "evidence:sha256:" + "2" * 64
BASELINE_REF = "context:sha256:" + "3" * 64
REVISION_REF = "revision:sha256:" + "4" * 64
OBSERVATION_REF = "observation:sha256:" + "5" * 64


@dataclass(frozen=True, slots=True)
class ReportFixture:
    context: AnalysisContext
    workspace: AnalysisWorkspace
    environment: dict[str, str]
    answer_text: str

    def with_audit_error(self) -> AnalysisContext:
        draft = ContextEventDraft(
            event_type="audit.diagnostic.recorded",
            turn_id=f"{self.workspace.analysis_id}-t001",
            payload={
                "message": "result_refs contains a non-result reference",
                "category": "answer_reference",
                "severity": "error",
                "reference": "evidence:sha256:" + "f" * 64,
                "impact": "audit impact",
                "remediation": "audit remediation",
            },
        )
        return _append_context_event(self.workspace, self.context, draft, integrity="diagnostic")


def test_report_renders_baseline_once_and_turn_context_deltas(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert report.count("## 仿真基线") == 1
    assert report.count("pandapower.networks.case39") == 1
    assert "## 分析执行上下文" in report
    assert "上下文版本：5 → 9" in report
    assert "复用前序结果" in report
    assert RESULT_REF in report
    assert "结果依赖关系" in report
    assert "context/analysis-context.json" in report
    assert "context/context-events.jsonl" in report


def test_report_keeps_submitted_answer_when_audit_has_errors(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.with_audit_error(),
        workspace=report_fixture.workspace,
        environment={},
    )

    assert report_fixture.answer_text in report
    assert "审计诊断" in report
    assert "模型草稿（未采纳）" not in report


def test_report_renders_failed_turns_and_unresolved_limitations(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "状态：failed" in report
    assert "执行限制 / execution limitation: solver unavailable" in report
    assert "## 未解决限制" in report
    assert "solver unavailable" in report


def test_report_deduplicates_multiple_baselines_by_source(tmp_path: Path) -> None:
    fixture = _build_report_fixture(tmp_path, include_second_baseline=True)

    report = render_analysis_report(context=fixture.context, workspace=fixture.workspace, environment={})

    assert report.count("## 仿真基线") == 1
    assert report.count("pandapower.networks.case39") == 1
    assert "补充基线 1 项" in report


def test_report_uses_relative_forensic_links_without_absolute_path_leakage(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "turns/001/answer.json" in report
    assert "evidence/results/powerflow.json" in report
    assert "evidence/analysis/powerflow-evidence.json" in report
    assert str(report_fixture.workspace.root_path) not in report
    assert str(report_fixture.workspace.root_path.parent) not in report


def test_report_rejects_absolute_and_traversal_artifact_paths(report_fixture: ReportFixture, tmp_path: Path) -> None:
    outside_answer = tmp_path / "outside-answer.json"
    outside_answer.write_text(
        json.dumps({"question_id": "outside", "answer_output": "外部答案不得读取"}, ensure_ascii=False),
        encoding="utf-8",
    )
    first_turn = report_fixture.context.turns[1].model_copy(update={"answer_path": str(outside_answer)})
    first_baseline = next(iter(report_fixture.context.baselines.values())).model_copy(update={"path": str(outside_answer)})
    first_result_key = next(iter(report_fixture.context.results))
    first_result = report_fixture.context.results[first_result_key].model_copy(update={"path": "../outside-result.json"})
    first_evidence_key = next(iter(report_fixture.context.evidence))
    first_evidence = report_fixture.context.evidence[first_evidence_key].model_copy(update={"path": "evidence/../secret.json"})
    context = report_fixture.context.model_copy(
        update={
            "turns": [
                report_fixture.context.turns[0],
                first_turn,
                *report_fixture.context.turns[2:],
            ],
            "baselines": {BASELINE_REF: first_baseline},
            "results": {first_result_key: first_result},
            "evidence": {first_evidence_key: first_evidence},
        }
    )

    report = render_analysis_report(context=context, workspace=report_fixture.workspace, environment={})

    assert "外部答案不得读取" not in report
    assert str(outside_answer) not in report
    assert "../outside-result.json" not in report
    assert "evidence/../secret.json" not in report
    assert report.count("路径不可用") >= 4
    assert "报告诊断" in report


def test_report_marks_turn_revision_unavailable_when_ledger_is_missing(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.context_events_path.unlink()

    report = render_analysis_report(context=report_fixture.context, workspace=report_fixture.workspace, environment={})

    assert "上下文版本：不可用" in report
    assert "事件账本不可用" in report
    assert "上下文版本：0 →" not in report


def test_report_marks_turn_revision_unavailable_when_ledger_is_malformed(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.context_events_path.write_text("{not-json}\n", encoding="utf-8")

    report = render_analysis_report(context=report_fixture.context, workspace=report_fixture.workspace, environment={})

    assert "上下文版本：不可用" in report
    assert "事件账本第 1 行格式错误" in report
    assert "上下文版本：0 →" not in report


def test_write_analysis_report_checkpoint_atomically_replaces_report(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.report_path.write_text("old report\n", encoding="utf-8")

    write_analysis_report_checkpoint(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first = report_fixture.workspace.report_path.read_text(encoding="utf-8")
    assert first.startswith("# 分析报告")
    assert "old report" not in first
    assert not list(report_fixture.workspace.root_path.glob(".report.md*.tmp"))


@dataclass(frozen=True, slots=True)
class _EventfulContext:
    context: AnalysisContext
    revisions: dict[str, tuple[int, int]]


def _build_report_fixture(tmp_path: Path, *, include_second_baseline: bool = False) -> ReportFixture:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-report")
    environment = {"provider": "test-provider", "model": "test-model", "pandapower": "3.4.0"}
    answer_text = "接受答案保持原文 result:sha256:" + "a" * 64

    answer_path = workspace.turn_path(1) / "answer.json"
    answer_path.write_text(
        json.dumps({"question_id": f"{workspace.analysis_id}-t001", "answer_output": answer_text}, ensure_ascii=False),
        encoding="utf-8",
    )
    (workspace.turn_path(1) / "answer-audit.json").write_text(
        json.dumps({"diagnostics": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    result_path = workspace.results_path / "powerflow.json"
    result_path.write_text(json.dumps({"ok": True}, ensure_ascii=False), encoding="utf-8")
    evidence_path = workspace.evidence_path / "analysis" / "powerflow-evidence.json"
    evidence_path.write_text(json.dumps({"ok": True}, ensure_ascii=False), encoding="utf-8")

    eventful = _build_context(workspace, answer_path=answer_path, include_second_baseline=include_second_baseline)
    workspace.context_snapshot_path.write_text(
        eventful.context.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    workspace.manifest_path.write_text(
        json.dumps({"analysis_id": workspace.analysis_id, "report": "report.md"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return ReportFixture(context=eventful.context, workspace=workspace, environment=environment, answer_text=answer_text)


def _build_context(
    workspace: AnalysisWorkspace,
    *,
    answer_path: Path,
    include_second_baseline: bool,
) -> _EventfulContext:
    state = initial_context(
        workspace.analysis_id,
        {
            "copied_path": "input/instructions.md.txt",
            "source_path": str(workspace.root_path.parent / "task.md.txt"),
            "sha256": "a" * 64,
            "instruction_count": 2,
        },
        {
            "provider": "test-provider",
            "model": "test-model",
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        },
    )
    revisions: dict[str, tuple[int, int]] = {}
    for draft in (
        ContextEventDraft(event_type="analysis.started", payload={"input": {}, "runtime": {}}),
        ContextEventDraft(
            event_type="turn.started",
            turn_id=f"{workspace.analysis_id}-t000",
            payload={
                "ordinal": 0,
                "instruction": "建立全局仿真基线",
                "instruction_sha256": "b" * 64,
                "nonce_sha256": "c" * 64,
            },
        ),
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id=f"{workspace.analysis_id}-t000",
            payload={
                "context_ref": BASELINE_REF,
                "revision_ref": REVISION_REF,
                "path": "evidence/contexts/context.json",
                "source": {"model": "ieee39", "source": "pandapower.networks.case39"},
                "network": {"engine": "pandapower", "pandapower_version": "3.4.0", "buses": 39, "lines": 35},
            },
        ),
        ContextEventDraft(
            event_type="turn.completed",
            turn_id=f"{workspace.analysis_id}-t000",
            payload={
                "status": "success",
                "answer_path": None,
                "answer_sha256": None,
                "duration_seconds": 0.1,
            },
        ),
        ContextEventDraft(
            event_type="turn.started",
            turn_id=f"{workspace.analysis_id}-t001",
            payload={
                "ordinal": 1,
                "instruction": "运行潮流并复用前序结果",
                "instruction_sha256": "b" * 64,
                "nonce_sha256": "c" * 64,
            },
        ),
        ContextEventDraft(
            event_type="result.registered",
            turn_id=f"{workspace.analysis_id}-t001",
            capability="analysis.powerflow.ac.run",
            payload={
                "result_ref": RESULT_REF,
                "revision_ref": REVISION_REF,
                "path": "evidence/results/powerflow.json",
                "evidence_refs": [],
                "solver_summary": {"converged": True},
                "producer_observation": {"trace_sequence": 7},
            },
        ),
        ContextEventDraft(
            event_type="evidence.registered",
            turn_id=f"{workspace.analysis_id}-t001",
            capability="analysis.powerflow.ac.run",
            payload={
                "evidence_ref": EVIDENCE_REF,
                "path": "evidence/analysis/powerflow-evidence.json",
                "kind": "simulator",
                "refs": [RESULT_REF],
                "summary": {"title": "潮流证据"},
            },
        ),
        ContextEventDraft(
            event_type="tool.observation.recorded",
            turn_id=f"{workspace.analysis_id}-t001",
            capability="result.branches.rank",
            payload={
                "observation_ref": OBSERVATION_REF,
                "path": "tool-results/rank.json",
                "summary": {"action": "复用前序结果", "ok": True},
                "producer_observation": {"trace_sequence": 8},
                "consumed_refs": [RESULT_REF],
                "produced_refs": [],
            },
        ),
        ContextEventDraft(
            event_type="turn.completed",
            turn_id=f"{workspace.analysis_id}-t001",
            payload={
                "status": "success",
                "answer_path": str(answer_path.relative_to(workspace.root_path)),
                "answer_sha256": "d" * 64,
                "duration_seconds": 1.5,
            },
        ),
        ContextEventDraft(
            event_type="turn.started",
            turn_id=f"{workspace.analysis_id}-t002",
            payload={
                "ordinal": 2,
                "instruction": "失败回合",
                "instruction_sha256": "e" * 64,
                "nonce_sha256": "f" * 64,
            },
        ),
        ContextEventDraft(
            event_type="limitation.recorded",
            turn_id=f"{workspace.analysis_id}-t002",
            payload={
                "limitation_ref": "limitation:solver",
                "message": "solver unavailable",
                "refs": [RESULT_REF],
            },
        ),
        ContextEventDraft(
            event_type="turn.completed",
            turn_id=f"{workspace.analysis_id}-t002",
            payload={
                "status": "failed",
                "answer_path": None,
                "answer_sha256": None,
                "duration_seconds": 0.2,
            },
        ),
    ):
        before = state.revision
        state = _append_context_event(workspace, state, draft, integrity="diagnostic" if draft.event_type == "limitation.recorded" else "verified")
        after = state.revision
        if draft.event_type == "turn.started" and draft.turn_id:
            revisions[draft.turn_id] = (before, after)
        elif draft.event_type == "turn.completed" and draft.turn_id:
            revisions[draft.turn_id] = (revisions[draft.turn_id][0], after)

    if include_second_baseline:
        turn = ContextEventDraft(
            event_type="turn.started",
            turn_id=f"{workspace.analysis_id}-t003",
            payload={
                "ordinal": 3,
                "instruction": "重复打开同一来源基线",
                "instruction_sha256": "1" * 64,
                "nonce_sha256": "2" * 64,
            },
        )
        state = _append_context_event(workspace, state, turn)
        state = _append_context_event(
            workspace,
            state,
            ContextEventDraft(
                event_type="simulator.context.opened",
                turn_id=turn.turn_id,
                payload={
                    "context_ref": "context:sha256:" + "9" * 64,
                    "revision_ref": "revision:sha256:" + "8" * 64,
                    "path": "evidence/contexts/context-2.json",
                    "source": {"model": "ieee39", "source": "pandapower.networks.case39"},
                    "network": {"engine": "pandapower", "pandapower_version": "3.4.0"},
                },
            ),
        )

    return _EventfulContext(context=state, revisions=revisions)


def _append_context_event(
    workspace: AnalysisWorkspace,
    state: AnalysisContext,
    draft: ContextEventDraft,
    *,
    integrity: str = "verified",
) -> AnalysisContext:
    next_state = reduce_context(state, draft)
    event = AnalysisContextEvent(
        **draft.model_dump(mode="json"),
        analysis_id=state.analysis_id,
        sequence=next_state.revision,
        previous_revision=state.revision,
        previous_state_hash=state.state_hash,
        next_revision=next_state.revision,
        next_state_hash=next_state.state_hash,
        integrity=integrity,  # type: ignore[arg-type]
    )
    with workspace.context_events_path.open("a", encoding="utf-8") as stream:
        stream.write(event.model_dump_json() + "\n")
    return next_state


@pytest.fixture
def report_fixture(tmp_path: Path) -> ReportFixture:
    return _build_report_fixture(tmp_path)
