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
from grid_agent.knowledge.offline import answer_diagnostic, answer_information
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
from grid_agent.tools.catalog import ToolCatalog, load_packaged_capability_documents
from grid_agent.tools.guide import GuideIndex


app = typer.Typer(add_completion=False)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


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


def _load_verified_answer_draft(workspace: RunWorkspace) -> str:
    draft_path = workspace.root_path / "answer-draft.json"
    if not draft_path.is_file():
        raise RuntimeError("grid_submit_answer did not create an answer draft")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("grid_submit_answer draft is not valid JSON") from exc
    if not isinstance(draft, dict):
        raise RuntimeError("grid_submit_answer draft must be a JSON object")
    answer = draft.get("answer_output")
    claimed = draft.get("claim_evidence_refs")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("grid_submit_answer draft must include answer_output")
    if not isinstance(claimed, list) or not all(isinstance(item, str) for item in claimed):
        raise RuntimeError("grid_submit_answer draft must include claim_evidence_refs")
    _verify_evidence_refs(workspace, tuple(claimed))
    return answer


def _verify_evidence_refs(workspace: RunWorkspace, evidence_refs: tuple[str, ...]) -> None:
    for evidence_ref in evidence_refs:
        if not evidence_ref.startswith("evidence:sha256:"):
            raise RuntimeError(f"claimed evidence ref is invalid: {evidence_ref}")
        digest = evidence_ref.removeprefix("evidence:sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(f"claimed evidence ref is invalid: {evidence_ref}")
        if not any(path.is_file() for path in workspace.evidence_path.rglob(f"*{digest}.json")):
            raise RuntimeError(f"claimed evidence ref is not in the current run: {evidence_ref}")


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
            gridctl = GridctlClient(
                executable=workspace.bin_path / "gridctl",
                workspace=workspace.root_path,
                timeout_seconds=60,
            )
            environment_description = gridctl.invoke("environment.describe", {})
            tool_catalog_path = ToolCatalog.from_environment(
                load_packaged_capability_documents(_repo_root()),
                environment_description,
            ).materialize(workspace.root_path / "tool-catalog.json")
            guide_index_path = GuideIndex.load(_repo_root() / "skills/grid-static-analysis").materialize(
                workspace.root_path / "guide-index.json"
            )
            PiConfigMaterializer(project_pi_dir).materialize(resolved)
            launch = build_pi_launch(
                resolved,
                RuntimePaths(
                    command=command,
                    project_pi_dir=project_pi_dir,
                    session_dir=workspace.pi_path,
                    workspace=workspace.root_path,
                    gridctl_dir=workspace.bin_path,
                    extension_path=_repo_root() / "packages/pi-grid-tools/src/domain-tools.mjs",
                    tool_catalog_path=tool_catalog_path,
                    guide_index_path=guide_index_path,
                    answer_draft_path=workspace.root_path / "answer-draft.json",
                    system_policy_path=_repo_root() / "configs/agent/system-policy.md",
                ),
                base_environment=runtime_environment,
            )
            rpc = PiRpcClient(launch, workspace, trace)
            rpc.start()
            try:
                rpc.prompt_and_wait(
                    request.question,
                    on_event=progress.on_event,
                    on_heartbeat=progress.heartbeat,
                    require_answer_text=False,
                )
                answer = _load_verified_answer_draft(workspace)
            finally:
                rpc.stop()
            progress.completed(answer)
            envelope = AnswerEnvelope(question_id=request.question_id, answer_output=answer)
            typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
            return
        answer = answer_information(request.question)
        if answer is None:
            executable = GridctlLocator(_repo_root()).resolve()
            workspace = RunWorkspace.create(project_paths.runs_dir, run_id=request.question_id)
            client = GridctlClient(executable=executable, workspace=workspace.root_path, timeout_seconds=60)
            answer = answer_diagnostic(request.question, client)
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
