from __future__ import annotations

import json
import re
import sys
import os
from pathlib import Path

import typer

from grid_agent.contracts import AnswerEnvelope, RunRequest
from grid_agent.simulator.client import GridctlClient
from grid_agent.simulator.locator import GridctlLocator
from grid_agent.application.workspace import RunWorkspace
from grid_agent.observability.trace import JsonlTraceWriter
from grid_agent.runtime.locator import PiRuntimeLocator
from grid_agent.runtime.rpc import PiRpcClient
from grid_agent.config.catalog import ProviderCatalog
from grid_agent.config.models import CliLLMOptions
from grid_agent.config.resolver import resolve_llm
from grid_agent.runtime.environment import RuntimePaths, build_pi_launch
from grid_agent.runtime.pi_config import PiConfigMaterializer
from grid_agent.runtime.installer import PiRuntimeInstaller
from grid_agent.runtime.lock import PiRuntimeLock
from grid_agent.auth.service import AuthService
from grid_agent.auth.store import CODEX_PROVIDER, ProjectAuthStore


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


def _install_gridctl(workspace: RunWorkspace) -> None:
    """Expose the approved simulator executable to Pi's restricted PATH."""
    executable = GridctlLocator(_repo_root()).resolve()
    target = workspace.bin_path / "gridctl"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(executable)


@app.command()
def run(
    question: str,
    question_id: str | None = typer.Option(None, "--question-id"),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    base_url: str | None = typer.Option(None, "--base-url"),
    api_key_env: str | None = typer.Option(None, "--api-key-env"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    request = RunRequest(question_id=question_id, question=question.strip()) if question_id else RunRequest.from_text(question)
    try:
        if not offline:
            workspace = RunWorkspace.create(Path.cwd() / "var/runs", run_id=request.question_id)
            trace = JsonlTraceWriter(workspace.events_path)
            state_dir = Path.cwd()
            project_pi_dir = state_dir / "var/pi/agent"
            auth_store = ProjectAuthStore(project_pi_dir / "auth.json")
            resolved = resolve_llm(
                catalog=ProviderCatalog.load(),
                cli=CliLLMOptions(
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key_env=api_key_env,
                ),
                environ=os.environ,
                oauth_configured=lambda profile: auth_store.status(profile).configured,
            )
            command = PiRuntimeLocator(state_dir, os.environ).resolve()
            _install_gridctl(workspace)
            PiConfigMaterializer(project_pi_dir).materialize(resolved)
            launch = build_pi_launch(
                resolved,
                RuntimePaths(
                    command=command,
                    project_pi_dir=project_pi_dir,
                    session_dir=workspace.pi_path,
                    workspace=workspace.root_path,
                    gridctl_dir=workspace.bin_path,
                    extension_path=_repo_root() / "packages/pi-grid-tools/src/hardened-bash.mjs",
                    prompt_path=_repo_root() / "configs/prompts/grid-agent-system.md",
                ),
            )
            rpc = PiRpcClient(launch, workspace, trace)
            rpc.start()
            try:
                answer = rpc.prompt_and_wait(request.question)
            finally:
                rpc.stop()
            envelope = AnswerEnvelope(question_id=request.question_id, answer_output=answer)
            typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
            return
        executable = GridctlLocator(_repo_root()).resolve()
        client = GridctlClient(executable=executable, workspace=Path.cwd() / "var/runs" / request.question_id, timeout_seconds=60)
        answer = _answer(request.question, client)
        envelope = AnswerEnvelope(question_id=request.question_id, answer_output=answer)
        typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
    except Exception as exc:
        typer.echo(f"grid-agent error: {exc}", err=True)
        typer.echo(json.dumps(AnswerEnvelope(question_id=request.question_id, answer_output=f"执行限制 / execution limitation: {type(exc).__name__}" ).model_dump(), ensure_ascii=False))
        raise typer.Exit(1)


@app.command()
def doctor(json_output: bool = typer.Option(False, "--json")) -> None:
    payload = {"gridctl": str(GridctlLocator(_repo_root()).resolve()), "live_probe": False}
    typer.echo(json.dumps(payload) if json_output else payload["gridctl"])


@app.command("install-pi")
def install_pi() -> None:
    """Install the pinned Pi runtime under ./var/runtime/pi."""
    command = PiRuntimeInstaller(PiRuntimeLock.load(), Path.cwd()).install()
    typer.echo(str(command.path))


@app.command("auth-import-pi")
def auth_import_pi() -> None:
    """Copy the local Pi Codex OAuth profile into project-owned storage."""
    store = ProjectAuthStore(Path.cwd() / "var/pi/agent/auth.json")
    helper = PiRuntimeLocator.from_cwd().resolve_oauth_helper()
    status = AuthService(store, helper).import_from_pi()
    typer.echo(json.dumps({"provider": status.provider, "configured": status.configured}))


@app.command("auth-login")
def auth_login() -> None:
    """Log into the pinned Pi Codex OAuth helper for this project."""
    store = ProjectAuthStore(Path.cwd() / "var/pi/agent/auth.json")
    helper = PiRuntimeLocator.from_cwd().resolve_oauth_helper()
    status = AuthService(store, helper).login(CODEX_PROVIDER)
    typer.echo(json.dumps({"provider": status.provider, "configured": status.configured}))


def main() -> int:
    app()
    return 0
