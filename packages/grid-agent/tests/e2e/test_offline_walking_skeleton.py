from __future__ import annotations

import json
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
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", question],
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
        ["uv", "run", "--project", "packages/grid-agent", "grid-agent", "run", "对线路171开展N-1校核;"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode != 0
    envelope = json.loads(completed.stdout)
    assert set(envelope) == {"question_id", "answer_output"}
    assert "limitation" in envelope["answer_output"]
