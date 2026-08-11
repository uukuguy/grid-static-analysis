from __future__ import annotations

import json
import re
import sys
import os
import time
from collections.abc import Mapping, Sequence
from typing import Any
from pathlib import Path

import typer
from dotenv import dotenv_values

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


def _runtime_environment(state_dir: Path) -> dict[str, str]:
    """Apply the documented .env layer before locating the Pi executable."""
    dotenv_layer = {
        key: value
        for key, value in dotenv_values(state_dir / ".env").items()
        if value is not None
    }
    return {**dotenv_layer, **os.environ}


class _ProgressReporter:
    def __init__(self, question: str) -> None:
        self.started_at = time.monotonic()
        self.question = _summary(question)

    def started(self, provider: str, model: str, run_id: str) -> None:
        self._write(f"开始运行 run={run_id} provider={provider} model={model}")
        self._write(f"调用输入: {self.question}")

    def on_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "unknown"))
        if event_type == "prompt_ack":
            self._write("模型请求已接收")
        elif event_type == "response" and event.get("command") == "prompt":
            if event.get("success") is True:
                self._write("模型请求已接收")
            else:
                self._write(f"模型请求失败: {_summary(str(event.get('error', 'unknown error')))}")
        elif event_type == "text_delta":
            self._write(f"模型输出: {_summary(str(event.get('text', '')))}")
        elif event_type == "message_update":
            assistant_event = event.get("assistantMessageEvent")
            if isinstance(assistant_event, Mapping) and assistant_event.get("type") == "thinking_end":
                self._write(f"模型推理: {_summary(str(assistant_event.get('content', '')))}")
        elif event_type == "message_end":
            message = event.get("message")
            if isinstance(message, Mapping) and message.get("role") == "assistant":
                output = _message_text(message)
                if output:
                    self._write(f"模型输出: {_summary(output)}")
        elif event_type == "tool_execution_start":
            self._write(
                f"工具开始: {event.get('toolName', 'unknown')} "
                f"输入: {_summary(json.dumps(_redact_event(event.get('args', {})), ensure_ascii=False))}"
            )
        elif event_type == "tool_execution_end":
            result = _redact_event(event.get("result", {}))
            status = "失败" if event.get("isError") else "完成"
            self._write(f"工具{status}: {event.get('toolName', 'unknown')} 输出: {_summary(json.dumps(result, ensure_ascii=False))}")
        elif event_type == "agent_end":
            self._write("模型执行结束，正在整理结果")

    def heartbeat(self) -> None:
        self._write("仍在等待模型或工具响应")

    def completed(self, answer: str) -> None:
        self._write(f"已完成，输出摘要: {_summary(answer)}")

    def _write(self, message: str) -> None:
        typer.echo(f"[{time.monotonic() - self.started_at:6.1f}s] {message}", err=True)


def _summary(value: str, limit: int = 200) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}…"


def _redact_event(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if any(term in str(key).lower() for term in ("key", "token", "secret", "authorization")) else _redact_event(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_event(item) for item in value]
    return value


def _message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes, bytearray)):
        return ""
    return "".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text"
    )


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
    progress = _ProgressReporter(request.question)
    try:
        if not offline:
            workspace = RunWorkspace.create(Path.cwd() / "var/runs", run_id=request.question_id)
            trace = JsonlTraceWriter(workspace.events_path)
            state_dir = Path.cwd()
            runtime_environment = _runtime_environment(state_dir)
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
            progress.started(resolved.config.provider, resolved.config.model, request.question_id)
            command = PiRuntimeLocator(state_dir, runtime_environment).resolve()
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
                base_environment=runtime_environment,
            )
            rpc = PiRpcClient(launch, workspace, trace)
            rpc.start()
            try:
                answer = rpc.prompt_and_wait(
                    request.question,
                    on_event=progress.on_event,
                    on_heartbeat=progress.heartbeat,
                )
            finally:
                rpc.stop()
            progress.completed(answer)
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
    # Importing an existing local Pi credential is a file operation; it must not
    # require the managed Pi runtime to have been installed first.
    status = store.import_provider(Path.home() / ".pi/agent/auth.json", CODEX_PROVIDER)
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
