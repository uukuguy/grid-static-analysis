from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from grid_agent.analysis.models import AnalysisContext, AnalysisContextEvent, ContextEventDraft
from grid_agent.analysis.reducer import initial_context, reduce_context
from grid_agent.analysis.report import (
    _read_trace_decisions,
    render_analysis_report,
    write_analysis_report_checkpoint,
)
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


def test_report_uses_per_question_narrative_and_real_trace_steps(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    assert report.startswith("# 系统仿真分析报告")
    assert "## 本批次运行环境" in report
    assert "## 1. 运行潮流并复用前序结果" in report
    assert report.index("### 回答") < report.index("### 仿真环境上下文")
    assert report.index("### 仿真环境上下文") < report.index("### 智能体分析轨迹")
    assert report.index("### 智能体分析轨迹") < report.index("### 执行状态与证据")
    assert "核查线路 11 两端母线" in report
    assert "母线 6 → 母线 11" in report
    assert "交流潮流" in report and "收敛" in report and "43.6275 MW" in report
    assert "查询 `network.branches`" in report
    assert "线路 11：132.51%" in report
    assert "执行单支路 N-1 静态安全校核" in report
    assert "35 个场景" in report and "132.51%" in report
    assert "### 执行状态与证据" in report
    assert "```json" not in report.split("### 执行状态与证据", maxsplit=1)[0]
    assert "result:sha256:" not in report
    assert "evidence:sha256:" not in report
    assert "结果依赖关系" not in report


def test_report_puts_answer_first_and_restores_simulation_context(
    report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    first_turn = report.split("## 1. 运行潮流并复用前序结果", maxsplit=1)[1].split(
        "## 2.", maxsplit=1
    )[0]
    answer_at = first_turn.index("### 回答")
    context_at = first_turn.index("### 仿真环境上下文")
    trajectory_at = first_turn.index("### 智能体分析轨迹")
    evidence_at = first_turn.index("### 执行状态与证据")

    assert answer_at < context_at < trajectory_at < evidence_at
    assert report_fixture.answer_text in first_turn[answer_at:context_at]
    assert "活动模型：IEEE-39" in first_turn[context_at:trajectory_at]
    assert "母线电压约束：0.94–1.06 p.u.（模型数据）" in first_turn[context_at:trajectory_at]
    assert "```json" not in first_turn[trajectory_at:evidence_at]
    assert "result:sha256:" not in first_turn
    assert "api_key" not in first_turn
    assert "authorization" not in first_turn
    assert "turns/001/trace.md" in first_turn


def test_report_keeps_main_report_compact_when_tool_results_include_nested_credentials(
    report_fixture: ReportFixture,
) -> None:
    report = render_report_with_tool_result(
        report_fixture,
        capability="analysis.future.operation",
        result={
            "vm_pu": 1.03,
            "p_mw": 24.5,
            "password": "must-not-leak",
            "passwd": "must-not-leak",
            "private-key": "must-not-leak",
            "clientSecret": "must-not-leak",
            "credentials": {"username": "operator", "apiKey": "must-not-leak"},
            "access_token": "must-not-leak",
            "refreshToken": "must-not-leak",
            "id_token": "must-not-leak",
            "nested": [
                {
                    "normal_label": "branch-11",
                    "x_api_key": "must-not-leak",
                    "passwordless_enabled": True,
                }
            ],
        },
    )

    first_turn = report.split("## 1. 运行潮流并复用前序结果", maxsplit=1)[1].split(
        "## 2.", maxsplit=1
    )[0]
    trajectory = first_turn.split("### 智能体分析轨迹", maxsplit=1)[1].split("### 执行状态与证据", maxsplit=1)[0]

    assert "analysis.future.operation" in trajectory
    assert "```json" not in trajectory
    assert "must-not-leak" not in report
    assert "clientSecret" not in report
    assert "private-key" not in report
    assert "credentials" not in report


def test_failed_turn_keeps_answer_first_context_and_successful_trajectory(
    failed_report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=failed_report_fixture.context,
        workspace=failed_report_fixture.workspace,
        environment={},
    )
    failed_turn = report.split("## 2. 失败回合", maxsplit=1)[1]
    assert failed_turn.index("模型未返回可接受的最终回答。") < failed_turn.index(
        "### 仿真环境上下文"
    )
    assert failed_turn.index("### 仿真环境上下文") < failed_turn.index(
        "### 智能体分析轨迹"
    )
    assert "核查线路 11 两端母线" in failed_turn
    assert "状态：未完成" in failed_turn


def test_unknown_capability_remains_readable_without_expanded_json(
    report_fixture: ReportFixture,
) -> None:
    report = render_report_with_tool_result(
        report_fixture,
        capability="analysis.future.operation",
        result={"novel_metric": 12.75, "unit": "kV"},
    )
    assert "analysis.future.operation" in report
    first_turn = report.split("## 2.", maxsplit=1)[0]
    trajectory = first_turn.split("### 智能体分析轨迹", maxsplit=1)[1].split("### 执行状态与证据", maxsplit=1)[0]
    assert "```json" not in trajectory


def test_report_keeps_historical_submit_events_readable(
    report_fixture: ReportFixture,
) -> None:
    report = render_report_with_tool_result(
        report_fixture,
        capability="grid_submit_answer",
        result={"ok": True},
    )
    assert "提交本题回答（`grid_submit_answer`，完成，0.25 秒）" in report


def test_report_attaches_optional_native_decision_events(report_fixture: ReportFixture) -> None:
    supported_ref = "result:sha256:" + "7" * 64
    _append_trace_call(
        report_fixture.workspace,
        sequence=42,
        call_id="supported-rank-call",
        capability="result.branches.rank",
        args={"result_ref": supported_ref, "metric": "loading_percent", "limit": 5},
        result={
            "result_ref": supported_ref,
            "rows": [{"line": 11, "loading_percent": 132.51}],
        },
        turn_id=f"{report_fixture.workspace.analysis_id}-t001",
    )
    with report_fixture.workspace.events_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event_type": "business.decision.declared",
                    "scope": {
                        "turn_id": f"{report_fixture.workspace.analysis_id}-t001",
                        "tool_call_id": "grid-record-decision-call",
                    },
                    "refs": {"consumed": [supported_ref]},
                    "payload": {
                        "intent": "识别过载线路",
                        "decision": "线路 11 超过模型约束 100%",
                        "next_action": "对线路 11 开展 N-1 校核",
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    assert "决策：线路 11 超过模型约束 100%；下一步：对线路 11 开展 N-1 校核" in first_turn


def test_report_omits_unmatched_decision_tool_event_with_diagnostic(
    report_fixture: ReportFixture,
) -> None:
    with report_fixture.workspace.events_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event_type": "business.decision.declared",
                    "scope": {
                        "turn_id": f"{report_fixture.workspace.analysis_id}-t001",
                        "tool_call_id": "grid-record-decision-call",
                    },
                    "refs": {"consumed": ["result:sha256:" + "8" * 64]},
                    "payload": {
                        "intent": "说明下一步",
                        "decision": "缺少支持的决策不得附着",
                        "next_action": "继续",
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    assert "缺少支持的决策不得附着" not in first_turn
    assert "显式决策缺少可验证支持，已从紧凑轨迹省略" in report


def test_report_does_not_attach_later_turn_decision_to_prior_turn_support(
    report_fixture: ReportFixture,
) -> None:
    with report_fixture.workspace.events_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event_type": "business.decision.declared",
                    "scope": {
                        "turn_id": f"{report_fixture.workspace.analysis_id}-t002",
                        "tool_call_id": "grid-record-decision-call",
                    },
                    "refs": {"consumed": [RESULT_REF]},
                    "payload": {
                        "intent": "复用前序潮流",
                        "decision": "后续回合决策不得显示在第一题",
                        "next_action": "继续",
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    assert "后续回合决策不得显示在第一题" not in first_turn


def test_report_folds_decision_recording_call_into_supporting_milestone_and_keeps_trace(
    report_fixture: ReportFixture,
) -> None:
    supported_ref = "result:sha256:" + "9" * 64
    _append_trace_call(
        report_fixture.workspace,
        sequence=42,
        call_id="supported-powerflow-call",
        capability="analysis.powerflow.ac.run",
        args={"operation": "powerflow.ac"},
        result={"converged": True, "result_ref": supported_ref},
        turn_id=f"{report_fixture.workspace.analysis_id}-t001",
    )
    _append_trace_call(
        report_fixture.workspace,
        sequence=44,
        call_id="grid-record-decision-call",
        capability="grid_record_decision",
        args={"intent": "判断潮流结果"},
        result={
            "intent": "判断潮流结果",
            "decision": "潮流结果支持继续分析",
            "next_action": "查询支路负载率",
            "refs": {"consumed": [supported_ref]},
        },
        turn_id=f"{report_fixture.workspace.analysis_id}-t001",
    )
    with report_fixture.workspace.events_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event_type": "business.decision.declared",
                    "scope": {
                        "turn_id": f"{report_fixture.workspace.analysis_id}-t001",
                        "tool_call_id": "grid-record-decision-call",
                    },
                    "refs": {"consumed": [supported_ref]},
                    "payload": {
                        "intent": "判断潮流结果",
                        "decision": "潮流结果支持继续分析",
                        "next_action": "查询支路负载率",
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    trajectory = first_turn.split("### 智能体分析轨迹", maxsplit=1)[1].split("### 执行状态与证据", maxsplit=1)[0]
    detail = (report_fixture.workspace.turn_path(1) / "trace.md").read_text(encoding="utf-8")

    assert "grid_record_decision" not in trajectory
    assert trajectory.count("潮流结果支持继续分析") == 1
    assert "决策：潮流结果支持继续分析；下一步：查询支路负载率" in trajectory
    assert "grid_record_decision" in detail
    assert "潮流结果支持继续分析" in detail


def test_read_trace_decisions_tolerates_malformed_and_incomplete_events(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            (
                "{not-json}",
                json.dumps(
                    {
                        "event_type": "business.decision.declared",
                        "scope": {"turn_id": "turn-1", "tool_call_id": "call-1"},
                        "refs": {"consumed": ["result:sha256:" + "a" * 64]},
                        "payload": {"intent": "检查", "decision": "保留", "next_action": "继续"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event_type": "business.decision.declared",
                        "scope": {"turn_id": "turn-1"},
                        "payload": {"intent": "", "decision": "缺失", "next_action": "跳过"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event_type": "business.decision.declared",
                        "scope": {},
                    },
                    ensure_ascii=False,
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    decisions, diagnostics = _read_trace_decisions(path)

    assert len(decisions) == 1
    assert decisions[0].turn_id == "turn-1"
    assert decisions[0].tool_call_id == "call-1"
    assert decisions[0].support_refs == ("result:sha256:" + "a" * 64,)
    assert decisions[0].decision == "保留"
    assert diagnostics == (
        "原生轨迹第 1 行格式错误",
        "原生轨迹第 3 行决策字段无效",
        "原生轨迹第 4 行决策事件不完整",
    )


def test_report_shows_global_evidence_referenced_by_the_turn(report_fixture: ReportFixture) -> None:
    evidence_key = next(iter(report_fixture.context.evidence))
    global_evidence = report_fixture.context.evidence[evidence_key].model_copy(update={"turn_id": None})
    first_turn = report_fixture.context.turns[1].model_copy(update={"produced_refs": [RESULT_REF, EVIDENCE_REF]})
    context = report_fixture.context.model_copy(
        update={
            "turns": [report_fixture.context.turns[0], first_turn, *report_fixture.context.turns[2:]],
            "evidence": {evidence_key: global_evidence},
        }
    )
    report = render_analysis_report(
        context=context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    evidence_section = report.split("## 1. 运行潮流并复用前序结果", maxsplit=1)[1].split("### 执行状态与证据", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]

    assert "本题生成" in evidence_section
    assert "潮流证据" in evidence_section
    assert "[查看证据工件]" in evidence_section
    assert "evidence/analysis/powerflow-evidence.json" in evidence_section


def test_report_writes_detailed_trace_page_with_refs_redacted_credentials_and_raw_link(report_fixture: ReportFixture) -> None:
    tool_result = report_fixture.workspace.tool_results_path / f"{report_fixture.workspace.analysis_id}-t001" / "compatibility" / "rank-call.json"
    tool_result.parent.mkdir(parents=True, exist_ok=True)
    tool_result.write_text(json.dumps({"result_ref": RESULT_REF, "branches": []}), encoding="utf-8")
    _append_trace_call(
        report_fixture.workspace,
        sequence=50,
        call_id="sensitive-message-call",
        capability="analysis.future.operation",
        args={
            "result_ref": RESULT_REF,
            "message": "Authorization: Bearer input-token-must-not-leak",
            "metadata": {
                "key": "input-field-key-must-not-leak",
                "monkey": "input-monkey-kept",
                "passwordless_enabled": True,
                "tokens": 2,
            },
        },
        result={
            "result_ref": RESULT_REF,
            "message": (
                "key=inline-key-must-not-leak; "
                "api_key=output-key-must-not-leak; "
                "password=output-password-must-not-leak"
            ),
            "nested": {
                "context_ref": BASELINE_REF,
                "key": "output-field-key-must-not-leak",
                "monkey": "output-monkey-kept",
                "passwordless_enabled": True,
                "tokens": 3,
                "token": "field-token-must-not-leak",
            },
        },
        turn_id=f"{report_fixture.workspace.analysis_id}-t001",
    )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    detail_path = report_fixture.workspace.turn_path(1) / "trace.md"
    detail = detail_path.read_text(encoding="utf-8")

    assert "详细执行轨迹" in report
    assert "turns/001/trace.md" in report
    assert "## 1. 按支路运行指标筛选和排序" in detail
    assert "### 输入" in detail
    assert "loading_percent" in detail
    assert "### 输出摘要" in detail
    assert RESULT_REF in detail
    assert BASELINE_REF in detail
    assert "input-field-key-must-not-leak" not in detail
    assert "output-field-key-must-not-leak" not in detail
    assert "inline-key-must-not-leak" not in detail
    assert "input-token-must-not-leak" not in detail
    assert "output-key-must-not-leak" not in detail
    assert "output-password-must-not-leak" not in detail
    assert "field-token-must-not-leak" not in detail
    assert "input-monkey-kept" in detail
    assert "output-monkey-kept" in detail
    assert '"passwordless_enabled": true' in detail
    assert '"tokens": 3' in detail
    assert "analysis.future.operation" in detail
    assert "tool-results/analysis-report-t001/compatibility/rank-call.json" in detail
    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    assert RESULT_REF not in first_turn
    assert BASELINE_REF not in first_turn
    assert "input-field-key-must-not-leak" not in report
    assert "output-field-key-must-not-leak" not in report
    assert "inline-key-must-not-leak" not in report
    assert "input-token-must-not-leak" not in report
    assert "output-key-must-not-leak" not in report


def test_report_uses_native_turn_scope_for_tools_without_context_observations(
    report_fixture: ReportFixture,
) -> None:
    call_id = "submit-call"
    with report_fixture.workspace.trace_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "sequence": 9,
                    "timestamp": "2026-08-14T00:00:02Z",
                    "event": "pi_event",
                    "payload": {
                        "type": "tool_execution_start",
                        "tool_call_id": call_id,
                        "tool_name": "grid_submit_answer",
                        "args": {"answer_output": "done"},
                    },
                }
            )
            + "\n"
        )
        stream.write(
            json.dumps(
                {
                    "sequence": 10,
                    "timestamp": "2026-08-14T00:00:03Z",
                    "event": "pi_event",
                    "payload": {
                        "type": "tool_result",
                        "tool_call_id": call_id,
                        "capability": "grid_submit_answer",
                        "ok": True,
                        "result": {"accepted": True},
                    },
                }
            )
            + "\n"
        )
    report_fixture.workspace.events_path.write_text(
        json.dumps(
            {
                "event_type": "tool.completed",
                "scope": {
                    "turn_id": f"{report_fixture.workspace.analysis_id}-t001",
                    "tool_call_id": call_id,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first_turn = report.split("## 1.", maxsplit=1)[1].split("## 2.", maxsplit=1)[0]
    assert "提交本题回答（`grid_submit_answer`，完成，1.00 秒）" in first_turn


def test_report_keeps_submitted_answer_when_audit_has_errors(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.with_audit_error(),
        workspace=report_fixture.workspace,
        environment={},
    )

    assert "接受答案保持原文" in report
    assert "〔可追溯引用〕" not in report
    assert "result:sha256:" not in report
    assert "## 完整性诊断" in report
    assert "模型草稿（未采纳）" not in report


def test_report_elides_internal_ids_without_leaving_reference_placeholders(
    report_fixture: ReportFixture,
) -> None:
    answer_path = report_fixture.workspace.turn_path(1) / "answer.json"
    answer_path.write_text(
        json.dumps(
            {
                "question_id": f"{report_fixture.workspace.analysis_id}-t001",
                "answer_output": (
                    "IEEE-39（pandapower case39，上下文 " + BASELINE_REF + "）中，"
                    "线路11（" + "asset:line:sha256:" + "6" * 64 + "）连接母线6与母线11。"
                    "证据引用 " + EVIDENCE_REF + "。"
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "IEEE-39（pandapower case39）中，线路11连接母线6与母线11。" in report
    assert "证据引用" not in report
    assert "〔可追溯引用〕" not in report
    assert "sha256:" not in report.split("<details>", maxsplit=1)[0]


def test_report_renders_failed_turns_and_unresolved_limitations(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "状态：未完成" in report
    assert "模型未返回可接受的最终回答。" in report
    assert "执行限制 / execution limitation" not in report
    assert "## 完整性诊断" in report
    assert "solver unavailable" in report

    failed_trace = (report_fixture.workspace.turn_path(2) / "trace.md").read_text(
        encoding="utf-8"
    )
    assert "### 失败诊断" in failed_trace
    assert "solver unavailable" in failed_trace


def test_report_preserves_reference_kind_when_redacting_failed_reference(
    report_fixture: ReportFixture,
) -> None:
    context = _append_context_event(
        report_fixture.workspace,
        report_fixture.context,
        ContextEventDraft(
            event_type="limitation.recorded",
            turn_id=f"{report_fixture.workspace.analysis_id}-t002",
            payload={
                "limitation_ref": "limitation:reference-kind",
                "message": f"declared result_ref is invalid: {EVIDENCE_REF}",
                "refs": [EVIDENCE_REF],
            },
        ),
        integrity="diagnostic",
    )

    report = render_analysis_report(
        context=context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "declared result_ref is invalid: [evidence 类型引用]" in report
    assert EVIDENCE_REF not in report


def test_report_deduplicates_multiple_baselines_by_source(tmp_path: Path) -> None:
    fixture = _build_report_fixture(tmp_path, include_second_baseline=True)

    report = render_analysis_report(context=fixture.context, workspace=fixture.workspace, environment={})

    assert report.count("## 本批次运行环境") == 1
    assert "## 完整性诊断" in report


def test_report_uses_relative_forensic_links_without_absolute_path_leakage(report_fixture: ReportFixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    assert "turns/001/answer.json" in report
    assert "context/analysis-context.json" in report
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
    assert report.count("路径不可用") >= 2
    assert "## 完整性诊断" in report


def test_report_marks_turn_revision_unavailable_when_ledger_is_missing(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.context_events_path.unlink()

    report = render_analysis_report(context=report_fixture.context, workspace=report_fixture.workspace, environment={})

    assert "上下文版本：不可用" not in report
    assert "事件账本不可用" in report


def test_report_marks_turn_revision_unavailable_when_ledger_is_malformed(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.context_events_path.write_text("{not-json}\n", encoding="utf-8")

    report = render_analysis_report(context=report_fixture.context, workspace=report_fixture.workspace, environment={})

    assert "上下文版本：不可用" not in report
    assert "事件账本第 1 行格式错误" in report


def test_write_analysis_report_checkpoint_atomically_replaces_report(report_fixture: ReportFixture) -> None:
    report_fixture.workspace.report_path.write_text("old report\n", encoding="utf-8")

    write_analysis_report_checkpoint(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )

    first = report_fixture.workspace.report_path.read_text(encoding="utf-8")
    assert first.startswith("# 系统仿真分析报告")
    assert "old report" not in first
    assert not list(report_fixture.workspace.root_path.glob(".report.md*.tmp"))


@dataclass(frozen=True, slots=True)
class _EventfulContext:
    context: AnalysisContext
    revisions: dict[str, tuple[int, int]]


def _build_report_fixture(tmp_path: Path, *, include_second_baseline: bool = False) -> ReportFixture:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-report")
    environment = {"provider": "test-provider", "model": "test-model", "pandapower": "3.4.0"}
    answer_text = "接受答案保持原文"

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
    workspace.trace_path.parent.mkdir(parents=True, exist_ok=True)
    workspace.trace_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "sequence": 7,
                        "timestamp": "2026-08-14T00:00:00Z",
                        "event": "pi_event",
                        "payload": {
                            "type": "tool_execution_start",
                            "tool_call_id": "rank-call",
                            "tool_name": "grid_result_branches_rank",
                            "args": {"result_ref": RESULT_REF, "metric": "loading_percent", "limit": 5},
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "sequence": 8,
                        "timestamp": "2026-08-14T00:00:01.500000Z",
                        "event": "pi_event",
                        "payload": {
                            "type": "tool_result",
                            "tool_call_id": "rank-call",
                            "tool_name": "grid_result_branches_rank",
                            "capability": "result.branches.rank",
                            "ok": True,
                            "result": {"result_ref": RESULT_REF, "metric": "loading_percent"},
                            "evidence_refs": [],
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _append_trace_call(
        workspace,
        sequence=10,
        call_id="endpoint-call",
        capability="topology.branch.endpoints.get",
        args={"branch_kind": "line", "branch_id": 11},
        result={
            "from_bus": 6,
            "to_bus": 11,
            "context_ref": BASELINE_REF,
            "api_key": "must-not-leak",
        },
        turn_id=f"{workspace.analysis_id}-t001",
    )
    _append_trace_call(
        workspace,
        sequence=12,
        call_id="powerflow-call",
        capability="analysis.powerflow.ac.run",
        args={"context_ref": BASELINE_REF},
        result={
            "converged": True,
            "total_active_loss": {"value": 43.6275, "unit": "MW"},
            "result_ref": RESULT_REF,
        },
        turn_id=f"{workspace.analysis_id}-t001",
    )
    _append_trace_call(
        workspace,
        sequence=14,
        call_id="dataset-call",
        capability="model.dataset.query",
        args={"dataset": "network.branches", "filters": {"line": 11}},
        result={
            "rows": [
                {
                    "line": 11,
                    "from_bus": 6,
                    "to_bus": 11,
                    "loading_percent": 132.51,
                    "authorization": "Bearer must-not-leak",
                }
            ]
        },
        turn_id=f"{workspace.analysis_id}-t001",
    )
    _append_trace_call(
        workspace,
        sequence=16,
        call_id="contingency-call",
        capability="analysis.contingency.n_minus_one.run",
        args={"context_ref": BASELINE_REF, "outage_kind": "single_branch"},
        result={"scenario_count": 35, "worst_loading_percent": 132.51},
        turn_id=f"{workspace.analysis_id}-t001",
    )
    _append_trace_call(
        workspace,
        sequence=18,
        call_id="failed-endpoint-call",
        capability="topology.branch.endpoints.get",
        args={"branch_kind": "line", "branch_id": 11},
        result={"from_bus": 6, "to_bus": 11},
        turn_id=f"{workspace.analysis_id}-t002",
    )
    return ReportFixture(context=eventful.context, workspace=workspace, environment=environment, answer_text=answer_text)


def render_report_with_tool_result(
    fixture: ReportFixture,
    *,
    capability: str,
    result: dict[str, object],
) -> str:
    call_id = f"{capability.replace('.', '-')}-call"
    _append_trace_call(
        fixture.workspace,
        sequence=40,
        call_id=call_id,
        capability=capability,
        args={"probe": capability},
        result=result,
        turn_id=f"{fixture.workspace.analysis_id}-t001",
    )
    return render_analysis_report(
        context=fixture.context,
        workspace=fixture.workspace,
        environment=fixture.environment,
    )


def _append_trace_call(
    workspace: AnalysisWorkspace,
    *,
    sequence: int,
    call_id: str,
    capability: str,
    args: dict[str, object],
    result: dict[str, object],
    turn_id: str,
) -> None:
    with workspace.trace_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "sequence": sequence,
                    "timestamp": "2026-08-14T00:00:02Z",
                    "event": "pi_event",
                    "payload": {
                        "type": "tool_execution_start",
                        "tool_call_id": call_id,
                        "tool_name": capability,
                        "args": args,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        stream.write(
            json.dumps(
                {
                    "sequence": sequence + 1,
                    "timestamp": "2026-08-14T00:00:02.250000Z",
                    "event": "pi_event",
                    "payload": {
                        "type": "tool_result",
                        "tool_call_id": call_id,
                        "tool_name": capability,
                        "capability": capability,
                        "ok": True,
                        "result": result,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    with workspace.events_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event_type": "tool.completed",
                    "scope": {
                        "turn_id": turn_id,
                        "tool_call_id": call_id,
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )


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
            event_type="domain.state.projected",
            turn_id=f"{workspace.analysis_id}-t000",
            capability="model.constraints.describe",
            payload={
                "projector": "model-constraints-v1",
                "model": {
                    "context_ref": BASELINE_REF,
                    "revision_ref": REVISION_REF,
                    "model_id": "ieee39",
                    "source": "pandapower.networks.case39",
                    "counts": {"bus": 39, "line": 35},
                },
                "constraints": [
                    {
                        "constraint_ref": "constraint:sha256:" + "6" * 64,
                        "context_ref": BASELINE_REF,
                        "revision_ref": REVISION_REF,
                        "quantity": "bus.vm_pu",
                        "subject_kind": "bus",
                        "lower": 0.94,
                        "upper": 1.06,
                        "unit": "p.u.",
                        "applies_to_count": 39,
                        "source_kind": "model",
                        "source_ref": "model:test",
                        "source": {"table": "bus"},
                        "producer_capability": "model.constraints.describe",
                        "producer_turn_id": f"{workspace.analysis_id}-t000",
                    }
                ],
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
            event_type="domain.state.projected",
            turn_id=f"{workspace.analysis_id}-t001",
            capability="analysis.powerflow.ac.run",
            payload={
                "projector": "powerflow-ac-v1",
                "calculations": [
                    {
                        "result_ref": RESULT_REF,
                        "kind": "powerflow.ac",
                        "context_ref": BASELINE_REF,
                        "revision_ref": REVISION_REF,
                        "status": "converged",
                        "artifact_path": "evidence/results/powerflow.json",
                        "producer_capability": "analysis.powerflow.ac.run",
                        "producer_turn_id": f"{workspace.analysis_id}-t001",
                    }
                ],
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


@pytest.fixture
def failed_report_fixture(tmp_path: Path) -> ReportFixture:
    return _build_report_fixture(tmp_path)
