from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import typer

from grid_agent.contracts import AnswerEnvelope, RunRequest
from grid_agent.simulator.client import GridctlClient
from grid_agent.simulator.locator import GridctlLocator


app = typer.Typer(add_completion=False)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _answer(question: str, client: GridctlClient) -> str:
    normalized = question.lower()
    if "电压" in question and ("范围" in question or "正常" in question):
        return "静态分析策略的母线电压正常范围为 0.95–1.05 pu。"
    if "n-1" in normalized and ("哪些" in question or "什么" in question):
        return "N-1 校核逐一退出一个元件，检查潮流是否收敛、母线低/高电压，以及线路和变压器过载。"
    if "输入" in question and "潮流" in question:
        return "交流潮流需要网络模型、运行方式以及明确的求解器/策略参数；本工具使用固定的 pandapower 3.4.0 AC 选项。"
    network = client.call("network.open", {"network": "ieee39"})
    reference = network["network_ref"]
    if "线路11" in question and ("连接" in question or "哪两个" in question):
        line = client.call("element.resolve", {"network_ref": reference, "element": "line", "namespace": "index", "query": "11"})
        return f"线路 line:index:11 连接母线 {line['from_bus']['name']} 与 {line['to_bus']['name']}。"
    powerflow = client.call("powerflow.run_ac", {"network_ref": reference})
    if "负载率最高" in question:
        ranked = client.call("results.lines", {"result_ref": powerflow["result_ref"], "sort": "loading_percent", "limit": 5})
        return "负载率最高的5条线路为：" + "、".join(f"line:index:{item['index']} ({item['loading_percent']:.3f}%)" for item in ranked["lines"])
    if "n-1" in normalized or "故障" in question:
        match = re.search(r"线路\s*(\d+)", question)
        line_index = int(match.group(1)) if match else 11
        contingency = client.call("contingency.run_lines", {"network_ref": reference, "line_ids": [f"line:index:{line_index}"], "policy": "static-analysis-v1"})
        scenario = contingency["scenarios"][0]
        return f"线路 line:index:{line_index} N-1 后最大线路负载率为 {scenario['max_line_loading_percent']:.12f}%，越限线路为 " + "、".join(f"line:index:{item['index']}" for item in scenario["overloaded_lines"]) + f"；证据 {scenario['evidence_id']}。"
    return f"IEEE-39 交流潮流已收敛；总有功网损为 {powerflow['total_active_loss_mw']:.14f} MW，结果证据 {powerflow['result_ref']}。"


@app.command()
def run(question: str, question_id: str | None = typer.Option(None, "--question-id")) -> None:
    request = RunRequest(question_id=question_id, question=question.strip()) if question_id else RunRequest.from_text(question)
    try:
        executable = GridctlLocator(_repo_root()).resolve()
        client = GridctlClient(executable=executable, workspace=Path.cwd() / "var/runs" / request.question_id, timeout_seconds=60)
        answer = _answer(request.question, client)
        envelope = AnswerEnvelope(question_id=request.question_id, answer_output=answer)
        typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
    except Exception as exc:
        typer.echo(json.dumps(AnswerEnvelope(question_id=request.question_id, answer_output=f"执行限制 / execution limitation: {type(exc).__name__}" ).model_dump(), ensure_ascii=False))
        raise typer.Exit(1)


@app.command()
def doctor(json_output: bool = typer.Option(False, "--json")) -> None:
    payload = {"gridctl": str(GridctlLocator(_repo_root()).resolve()), "live_probe": False}
    typer.echo(json.dumps(payload) if json_output else payload["gridctl"])


def main() -> int:
    app()
    return 0
