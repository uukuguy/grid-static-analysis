from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("IEEE-39节点系统中线路11连接哪两个母线?", ("6", "11", "evidence:")),
        ("母线电压正常运行范围是多少?", ("0.95", "1.05")),
        ("N-1静态安全校核需要检查哪些越限类型?", ("电压", "过载")),
    ],
)
def test_offline_examples_return_strict_envelopes(question: str, expected: tuple[str, ...]) -> None:
    completed = subprocess.run(
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "--offline", question],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert set(envelope) == {"question_id", "answer_output"}
    assert all(value in envelope["answer_output"] for value in expected)


@pytest.mark.parametrize(
    "question_id,question,expected",
    [
        (
            "task7-powerflow-limitation-e2e",
            "对IEEE-39节点系统运行交流潮流，并输出有功网损;",
            ("Task7", "analysis.powerflow.ac.run", "交流潮流"),
        ),
        (
            "task7-ranking-limitation-e2e",
            "筛选负载率最高的5条线路;",
            ("Task7", "result.branches.rank", "负载率排序"),
        ),
        (
            "task7-n1-limitation-e2e",
            "对线路171开展N-1校核;",
            ("Task7", "analysis.contingency.n_minus_one.run", "N-1"),
        ),
        (
            "task7-fault-ranking-limitation-e2e",
            "对关键线路逐一进行故障分析并排序;",
            ("Task7", "analysis.contingency.n_minus_one.run", "result.branches.rank", "故障分析"),
        ),
    ],
)
def test_offline_task7_analysis_forms_return_limitation_without_run_artifacts(
    question_id: str, question: str, expected: tuple[str, ...]
) -> None:
    runs_path = ROOT / "runs" / question_id
    shutil.rmtree(runs_path, ignore_errors=True)

    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "packages/grid-agent",
                "grid-agent",
                "run",
                "--offline",
                "--question-id",
                question_id,
                question,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )

        assert completed.returncode == 0, completed.stderr
        envelope = json.loads(completed.stdout)
        assert set(envelope) == {"question_id", "answer_output"}
        assert envelope["question_id"] == question_id
        assert all(value in envelope["answer_output"] for value in expected)
        assert "execution limitation" in envelope["answer_output"]
        assert not runs_path.exists()
    finally:
        shutil.rmtree(runs_path, ignore_errors=True)


def test_offline_runs_write_operator_visible_runs_layout() -> None:
    question_id = "path-layout-e2e"
    runs_path = ROOT / "runs" / question_id
    shutil.rmtree(runs_path, ignore_errors=True)

    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                "packages/grid-agent",
                "grid-agent",
                "run",
                "--offline",
                "--question-id",
                question_id,
                "IEEE-39节点系统中线路11连接哪两个母线?",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )

        assert completed.returncode == 0, completed.stderr
        assert "母线 6 与 11" in json.loads(completed.stdout)["answer_output"]
        assert runs_path.is_dir()
    finally:
        shutil.rmtree(runs_path, ignore_errors=True)


def test_scripted_pi_traverses_real_gridctl(tmp_path: Path) -> None:
    gridctl = ROOT / "packages/grid-simulator/.venv/bin/gridctl"
    pi = tmp_path / "scripted-pi"
    pi.write_text(
        "#!/usr/bin/env python3\nimport json,subprocess,sys,os\n"
        "request=json.loads(sys.stdin.readline())\n"
        f"gridctl={str(gridctl)!r}\n"
        "def call(capability,args):\n r=subprocess.run([gridctl,'request','--workspace',os.environ['GRID_AGENT_WORKSPACE']],input=json.dumps({'protocol_version':'1.0','request_id':capability,'capability':capability,'arguments':args})+'\\n',text=True,capture_output=True,check=True); return json.loads(r.stdout)['result']\n"
        "opened=call('context.open',{'model_id':'ieee39'})\nresult=call('topology.branch.endpoints.get',{'context_ref':opened['context_ref'],'kind':'line','namespace':'pandapower_index','identifier':'11'})\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}),flush=True)\nprint(json.dumps({'type':'text_delta','text':result['from_bus']['name']+'-'+result['to_bus']['name']}),flush=True)\nprint(json.dumps({'type':'agent_end'}),flush=True)\n",
        encoding="utf-8",
    )
    pi.chmod(0o755)
    completed = subprocess.run(
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "line 11 endpoints"],
        cwd=ROOT,
        env={
            **os.environ,
            "GRID_AGENT_PI_COMMAND": str(pi),
            "GRID_AGENT_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-only-secret",
        },
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "6-11" in json.loads(completed.stdout)["answer_output"]
    assert "模型请求已接收" in completed.stderr
    assert "已完成" in completed.stderr
