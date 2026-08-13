from __future__ import annotations

import json
import sys
from pathlib import Path

from grid_agent.cli.app import _run_child_with_live_stderr
from grid_agent.reporting import BatchRecord, load_questions, read_run_observations, render_markdown, write_jsonl


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
        steps=(("context.open", 0.2), ("topology.branch.endpoints.get", 0.6)),
        evidence_refs=("evidence:sha256:" + "a" * 64,),
        result_refs=(),
        error=None,
    )

    report = render_markdown(
        batch_id="batch-1",
        source_name="questions.txt",
        environment={"provider": "deepseek", "model": "deepseek-v4-flash", "pandapower": "3.4.0"},
        records=(record,),
    )

    assert "# 系统仿真分析报告" in report
    assert "问题 1" in report
    assert "任务拆解（基于实际执行）" in report
    assert "仿真环境" in report
    assert "证据来源" in report
    assert "topology.branch.endpoints.get" in report
    assert "线路11连接母线6与11。" in report


def test_write_jsonl_contains_only_answer_envelopes(tmp_path: Path) -> None:
    destination = tmp_path / "answers.jsonl"
    records = (
        BatchRecord(1, "q", "q-1", "a", "success", 1.0, None, (), (), (), None),
        BatchRecord(2, "q2", "q-2", "b", "failed", 2.0, None, (), (), (), "timeout"),
    )

    write_jsonl(destination, records)

    assert [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()] == [
        {"question_id": "q-1", "answer_output": "a"},
        {"question_id": "q-2", "answer_output": "b"},
    ]


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

    steps, evidence_refs, result_refs = read_run_observations(events.parent)

    assert steps == (("topology.branch.endpoints.get", 2.0),)
    assert evidence_refs == ("evidence:sha256:" + "a" * 64,)
    assert result_refs == ()


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
