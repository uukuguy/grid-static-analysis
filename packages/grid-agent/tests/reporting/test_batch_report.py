from __future__ import annotations

import json
import sys
from pathlib import Path

from grid_agent.cli.app import _question_boundary, _run_child_with_live_stderr
from grid_agent.reporting import (
    AnalysisStep,
    BatchRecord,
    EvidenceSource,
    RunObservation,
    SimulationContext,
    load_questions,
    read_run_observations,
    render_markdown,
    write_jsonl,
    append_jsonl_record,
)


def test_load_questions_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    source = tmp_path / "questions.txt"
    source.write_text("# title\n\n线路11连接哪两个母线?\n  母线电压范围?  \n", encoding="utf-8")

    assert load_questions(source) == ("线路11连接哪两个母线?", "母线电压范围?")


def test_render_markdown_explains_observed_analysis_environment_and_evidence() -> None:
    record = BatchRecord(
        ordinal=1,
        question="线路11连接哪两个母线?",
        question_id="q-1",
        answer_output="线路11连接母线6与11。",
        status="success",
        duration_seconds=4.2,
        run_path="runs/q-1",
        observation=RunObservation(
            context=SimulationContext(
                "context:sha256:" + "b" * 64,
                "ieee39",
                "pandapower.networks.case39",
                "pandapower",
                "3.4.0",
                "c" * 64,
                {"buses": 39, "lines": 35},
            ),
            steps=(
                AnalysisStep("context.open", 0.2, "打开只读网络仿真环境上下文：ieee39", True),
                AnalysisStep("topology.branch.endpoints.get", 0.6, "核查支路两端母线：已返回线路端点和可追溯网络事实", True),
            ),
            evidence_sources=(EvidenceSource("evidence:sha256:" + "a" * 64, "网络拓扑事实：已持久化该支路两端母线的来源记录", "topology.branch.endpoints.get", None, "evidence/network-facts/network-fact.json"),),
            result_refs=(),
        ),
        error=None,
    )

    report = render_markdown(
        batch_id="batch-1",
        source_name="questions.txt",
        environment={"provider": "deepseek", "model": "deepseek-v4-flash", "pandapower": "3.4.0"},
        records=(record,),
    )

    assert "# 系统仿真分析报告" in report
    assert "## 1. 线路11连接哪两个母线?" in report
    assert report.index("### 回答") < report.index("### 执行信息")
    assert "仿真环境上下文" in report
    assert "证据来源" in report
    assert "打开只读网络仿真环境上下文" in report
    assert "线路11连接母线6与11。" in report


def test_write_jsonl_contains_only_answer_envelopes(tmp_path: Path) -> None:
    destination = tmp_path / "answers.jsonl"
    records = (
        BatchRecord(1, "q", "q-1", "a", "success", 1.0, None, RunObservation(None, (), (), ()), None),
        BatchRecord(2, "q2", "q-2", "b", "failed", 2.0, None, RunObservation(None, (), (), ()), "timeout"),
    )

    write_jsonl(destination, records)

    assert [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()] == [
        {"question_id": "q-1", "answer_output": "a"},
        {"question_id": "q-2", "answer_output": "b"},
    ]


def test_append_jsonl_record_is_visible_before_the_next_question(tmp_path: Path) -> None:
    destination = tmp_path / "answers.jsonl"
    record = BatchRecord(1, "q", "q-1", "a", "success", 1.0, None, RunObservation(None, (), (), ()), None)

    append_jsonl_record(destination, record)

    assert destination.read_text(encoding="utf-8") == '{"question_id": "q-1", "answer_output": "a"}\n'


def test_question_boundary_scopes_live_child_logs_to_one_question() -> None:
    assert _question_boundary(1, 2, "线路11连接哪两个母线?", "开始") == "========== 问题 1/2 开始：线路11连接哪两个母线? =========="


def test_read_run_observations_pairs_tool_start_and_canonical_result(tmp_path: Path) -> None:
    events = tmp_path / "run/events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {"timestamp": "2026-08-13T00:00:01Z", "payload": {"type": "tool_execution_start", "toolName": "grid_topology_branch_endpoints"}},
                {"timestamp": "2026-08-13T00:00:03Z", "payload": {"event": "tool_result", "capability": "topology.branch.endpoints.get", "ok": True, "result": {"evidence_ref": "evidence:sha256:" + "a" * 64}, "evidence_refs": []}},
            )
        ),
        encoding="utf-8",
    )

    observation = read_run_observations(events.parent)

    assert observation.steps[0].capability == "topology.branch.endpoints.get"
    assert observation.steps[0].duration_seconds == 2.0
    assert observation.evidence_sources[0].reference == "evidence:sha256:" + "a" * 64
    assert observation.result_refs == ()


def test_batch_child_forwards_stderr_lines_before_process_completion(tmp_path: Path) -> None:
    script = (
        "import json,sys,time\n"
        "print('模型推理: 正在识别线路', file=sys.stderr, flush=True)\n"
        "time.sleep(0.03)\n"
        "print('工具开始: topology.branch.endpoints.get', file=sys.stderr, flush=True)\n"
        "print(json.dumps({'question_id':'q-1','answer_output':'答案'}), flush=True)\n"
    )
    observed: list[str] = []

    completed = _run_child_with_live_stderr([sys.executable, "-c", script], tmp_path, observed.append)

    assert observed == ["模型推理: 正在识别线路", "工具开始: topology.branch.endpoints.get"]
    assert json.loads(completed.stdout)["answer_output"] == "答案"
