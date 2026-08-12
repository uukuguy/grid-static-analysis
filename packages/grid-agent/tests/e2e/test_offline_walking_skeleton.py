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


def test_information_answer_creates_no_run_directory() -> None:
    question_id = "offline-info-no-run-e2e"
    runs_path = ROOT / "runs" / question_id
    shutil.rmtree(runs_path, ignore_errors=True)

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
            "母线电压正常运行范围是多少?",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert "0.95" in envelope["answer_output"] and "1.05" in envelope["answer_output"]
    assert not runs_path.exists()


@pytest.mark.parametrize(
    "question_id,question,expected",
    [
        (
            "unsupported-ieee118-ac-e2e",
            "对IEEE-118节点系统运行交流潮流，并输出有功网损;",
            ("执行限制", "IEEE-118"),
        ),
        (
            "unsupported-line171-n1-e2e",
            "对IEEE-39节点系统线路171开展N-1校核;",
            ("执行限制", "线路171"),
        ),
        (
            "ambiguous-n1-no-run-e2e",
            "开展N-1静态安全校核;",
            ("执行限制", "N-1"),
        ),
    ],
)
def test_offline_diagnostic_rejects_unsupported_or_ambiguous_requests_without_runs(
    question_id: str, question: str, expected: tuple[str, ...]
) -> None:
    runs_path = ROOT / "runs" / question_id
    shutil.rmtree(runs_path, ignore_errors=True)

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
    assert all(value in envelope["answer_output"] for value in expected)
    assert not runs_path.exists()


@pytest.mark.parametrize(
    "question_id,question,expected",
    [
        (
            "semantic-powerflow-e2e",
            "对IEEE-39节点系统运行交流潮流，并输出有功网损;",
            ("交流潮流已收敛", "有功网损", "MW", "evidence:"),
        ),
        (
            "semantic-ranking-e2e",
            "筛选IEEE-39节点系统负载率最高的5条线路;",
            ("负载率最高", "5", "线路", "%", "evidence:"),
        ),
        (
            "semantic-n1-e2e",
            "对IEEE-39节点系统线路11开展N-1校核;",
            ("N-1", "线路 11", "evidence:"),
        ),
    ],
)
def test_offline_analysis_forms_use_semantic_capabilities_with_evidence(
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
        assert list((runs_path / "evidence").rglob("*.json"))
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
        "def call(capability,args):\n r=subprocess.run([gridctl,'request','--workspace',os.environ['GRID_AGENT_WORKSPACE']],input=json.dumps({'protocol':'grid-capability','protocol_version':'1.0','request_id':capability,'capability':capability,'arguments':args})+'\\n',text=True,capture_output=True,check=True); return json.loads(r.stdout)['result']\n"
        "opened=call('context.open',{'model_id':'ieee39'})\nresult=call('topology.branch.endpoints.get',{'context_ref':opened['context_ref'],'kind':'line','namespace':'pandapower_index','identifier':'11'})\n"
        "draft={'answer_output':result['from_bus']['name']+'-'+result['to_bus']['name']+' '+result['evidence_ref'],'claim_evidence_refs':[result['evidence_ref']]}\n"
        "open(os.environ['GRID_AGENT_ANSWER_DRAFT'],'w',encoding='utf-8').write(json.dumps(draft))\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}),flush=True)\nprint(json.dumps({'type':'text_delta','text':'ignored free text'}),flush=True)\nprint(json.dumps({'type':'agent_end'}),flush=True)\n",
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


def test_online_path_requires_grid_submit_answer_draft(tmp_path: Path) -> None:
    pi = tmp_path / "scripted-pi-no-draft"
    pi.write_text(
        "#!/usr/bin/env python3\nimport json\njson.loads(input())\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}),flush=True)\n"
        "print(json.dumps({'type':'text_delta','text':'free-form answer'}),flush=True)\n"
        "print(json.dumps({'type':'agent_end'}),flush=True)\n",
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

    assert completed.returncode == 1
    envelope = json.loads(completed.stdout)
    assert set(envelope) == {"question_id", "answer_output"}
    assert envelope["answer_output"] == "执行限制 / execution limitation: RuntimeError"
    assert "grid_submit_answer did not create an answer draft" in completed.stderr


def test_online_path_accepts_submit_answer_without_free_text(tmp_path: Path) -> None:
    pi = tmp_path / "scripted-pi-draft-only"
    pi.write_text(
        "#!/usr/bin/env python3\nimport json, os\njson.loads(input())\n"
        "draft={'answer_output':'执行限制 / execution limitation: scripted draft','claim_evidence_refs':[]}\n"
        "open(os.environ['GRID_AGENT_ANSWER_DRAFT'],'w',encoding='utf-8').write(json.dumps(draft))\n"
        "print(json.dumps({'type':'response','command':'prompt','success':True}),flush=True)\n"
        "print(json.dumps({'type':'agent_end'}),flush=True)\n",
        encoding="utf-8",
    )
    pi.chmod(0o755)

    completed = subprocess.run(
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "unsupported scripted request"],
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
    assert json.loads(completed.stdout)["answer_output"] == "执行限制 / execution limitation: scripted draft"
