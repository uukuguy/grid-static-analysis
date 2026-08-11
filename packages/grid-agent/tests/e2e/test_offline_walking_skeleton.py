from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("IEEE-39节点系统中线路11连接哪两个母线?", ("6", "11")),
        ("母线电压正常运行范围是多少?", ("0.95", "1.05")),
        ("N-1静态安全校核需要检查哪些越限类型?", ("电压", "过载")),
        ("对IEEE-39节点系统运行交流潮流，并输出有功网损;", ("43.641", "MW")),
        ("筛选负载率最高的5条线路;", ("line:index:21", "line:index:29")),
        ("对关键线路逐一进行故障分析并排序;", ("evidence:", "line:index:7")),
    ],
)
def test_offline_examples_return_strict_envelopes(question: str, expected: tuple[str, str]) -> None:
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


def test_unknown_line_returns_a_truthful_limitation_envelope() -> None:
    completed = subprocess.run(
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "--offline", "对线路171开展N-1校核;"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode != 0
    envelope = json.loads(completed.stdout)
    assert set(envelope) == {"question_id", "answer_output"}
    assert "limitation" in envelope["answer_output"]


def test_scripted_pi_traverses_real_gridctl(tmp_path: Path) -> None:
    gridctl = ROOT / "packages/grid-simulator/.venv/bin/gridctl"
    pi = tmp_path / "scripted-pi"
    pi.write_text(
        "#!/usr/bin/env python3\nimport json,subprocess,sys,os\n"
        "request=json.loads(sys.stdin.readline())\n"
        f"gridctl={str(gridctl)!r}\n"
        "def call(operation,args):\n r=subprocess.run([gridctl,'request','--workspace',os.environ['GRID_AGENT_WORKSPACE']],input=json.dumps({'protocol_version':'1.0','request_id':operation,'operation':operation,'arguments':args})+'\\n',text=True,capture_output=True,check=True); return json.loads(r.stdout)['result']\n"
        "opened=call('network.open',{'network':'ieee39'})\nresult=call('powerflow.run_ac',{'network_ref':opened['network_ref']})\n"
        "print(json.dumps({'type':'prompt_ack','ok':True}),flush=True)\nprint(json.dumps({'type':'text_delta','text':str(result['total_active_loss_mw'])}),flush=True)\nprint(json.dumps({'type':'agent_end'}),flush=True)\n",
        encoding="utf-8",
    )
    pi.chmod(0o755)
    completed = subprocess.run(["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "run power flow"], cwd=ROOT, env={**os.environ, "GRID_AGENT_PI_COMMAND": str(pi), "OPENAI_API_KEY": "test-only-secret"}, text=True, capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert "43.641" in json.loads(completed.stdout)["answer_output"]
