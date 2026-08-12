from __future__ import annotations

import json
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
from grid_agent.application.paths import ProjectPaths
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
    task7_limitation = _task7_limitation(question)
    if task7_limitation is not None:
        return task7_limitation
    context = client.call("context.open", {"model_id": "ieee39"})
    context_ref = str(context["context_ref"])
    if "线路11" in question and ("连接" in question or "哪两个" in question):
        line = client.call(
            "topology.branch.endpoints.get",
            {"context_ref": context_ref, "kind": "line", "namespace": "pandapower_index", "identifier": "11"},
        )
        return (
            f"线路 {line['branch']['alias']} 连接母线 {line['from_bus']['name']} 与 {line['to_bus']['name']}；"
            f"证据 {line['evidence_ref']}。"
        )
    powerflow = client.call("analysis.powerflow.ac.run", {"context_ref": context_ref, "solver": "pandapower.runpp"})
    return f"IEEE-39 交流潮流已收敛；总有功网损为 {powerflow['total_active_loss_mw']:.14f} MW，结果证据 {powerflow['result_ref']}。"


def _task7_limitation(question: str) -> str | None:
    normalized = question.lower()
    if "负载率最高" in question:
        return (
            "执行限制 / execution limitation: Task7 result.branches.rank 负载率排序能力尚不可用；"
            "当前离线路径不会运行交流潮流、排序或生成仿真证据。"
        )
    if "n-1" in normalized or "故障" in question:
        capabilities = "analysis.contingency.n_minus_one.run"
        if "排序" in question:
            capabilities = f"{capabilities} 与 result.branches.rank"
        return (
            f"执行限制 / execution limitation: Task7 {capabilities} 故障分析/N-1 静态安全校核能力尚不可用；"
            "当前离线路径不会执行故障校核、风险排序或生成仿真证据。"
        )
    if "潮流" in question and any(term in question for term in ("运行", "输出", "网损", "有功")):
        return (
            "执行限制 / execution limitation: Task7 analysis.powerflow.ac.run 交流潮流分析能力尚不可用；"
            "当前离线路径不会运行潮流计算或生成仿真证据。"
        )
    return None


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

    def started(self, provider: str, model: str, run_id: str, *, timeout_seconds: float, max_retries: int) -> None:
        self._write(
            f"开始运行 run={run_id} provider={provider} model={model} "
            f"请求超时={timeout_seconds:g}s SDK重试={max_retries}次"
        )
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
        elif event_type == "auto_retry_start":
            self._write(
                f"模型请求失败，{event.get('delayMs', 0) / 1000:g}s 后第 "
                f"{event.get('attempt', '?')}/{event.get('maxAttempts', '?')} 次重试: "
                f"{_summary(str(event.get('errorMessage', 'unknown error')))}"
            )
        elif event_type == "auto_retry_end" and event.get("success") is False:
            self._write(f"模型重试失败: {_summary(str(event.get('finalError', 'unknown error')))}")
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
    project_paths = ProjectPaths.from_root(Path.cwd())
    try:
        if not offline:
            workspace = RunWorkspace.create(project_paths.runs_dir, run_id=request.question_id)
            trace = JsonlTraceWriter(workspace.events_path)
            runtime_environment = _runtime_environment(project_paths.root)
            project_pi_dir = project_paths.pi_agent_dir
            auth_store = ProjectAuthStore.from_pi_agent_dir(project_pi_dir)
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
            progress.started(
                resolved.config.provider,
                resolved.config.model,
                request.question_id,
                timeout_seconds=resolved.config.timeout_seconds,
                max_retries=resolved.config.max_retries,
            )
            runtime_lock = PiRuntimeLock.load(project_paths.runtime_lock)
            command = PiRuntimeLocator(project_paths.pi_runtime_dir, runtime_environment, runtime_lock=runtime_lock).resolve()
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
        client = GridctlClient(executable=executable, workspace=project_paths.runs_dir / request.question_id, timeout_seconds=60)
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
    """Install the pinned Pi runtime under the project internal state directory."""
    project_paths = ProjectPaths.from_root(Path.cwd())
    command = PiRuntimeInstaller(PiRuntimeLock.load(project_paths.runtime_lock), project_paths.pi_runtime_dir).install()
    typer.echo(str(command.path))


@app.command("auth-import-pi")
def auth_import_pi() -> None:
    """Copy the local Pi Codex OAuth profile into project-owned storage."""
    store = ProjectAuthStore.from_pi_agent_dir(ProjectPaths.from_root(Path.cwd()).pi_agent_dir)
    # Importing an existing local Pi credential is a file operation; it must not
    # require the managed Pi runtime to have been installed first.
    status = store.import_provider(Path.home() / ".pi/agent/auth.json", CODEX_PROVIDER)
    typer.echo(json.dumps({"provider": status.provider, "configured": status.configured}))


@app.command("auth-login")
def auth_login() -> None:
    """Log into the pinned Pi Codex OAuth helper for this project."""
    project_paths = ProjectPaths.from_root(Path.cwd())
    store = ProjectAuthStore.from_pi_agent_dir(project_paths.pi_agent_dir)
    helper = PiRuntimeLocator(
        project_paths.pi_runtime_dir,
        _runtime_environment(project_paths.root),
        runtime_lock=PiRuntimeLock.load(project_paths.runtime_lock),
    ).resolve_oauth_helper()
    status = AuthService(store, helper).login(CODEX_PROVIDER)
    typer.echo(json.dumps({"provider": status.provider, "configured": status.configured}))


def main() -> int:
    app()
    return 0
