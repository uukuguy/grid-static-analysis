from __future__ import annotations

import hashlib
import json
import sys
import os
import time
import subprocess
from datetime import UTC, datetime
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from pathlib import Path

import typer
from dotenv import dotenv_values

from grid_agent.contracts import AnswerEnvelope, RunRequest
from grid_agent.knowledge.offline import answer_diagnostic, answer_information, plan_diagnostic
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
from grid_agent.reporting import BatchRecord, load_questions, read_run_observations, render_markdown, write_jsonl


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
    result_refs = draft.get("result_refs")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("grid_submit_answer draft must include answer_output")
    if not isinstance(claimed, list) or not all(isinstance(item, str) for item in claimed):
        raise RuntimeError("grid_submit_answer draft must include claim_evidence_refs")
    if not isinstance(result_refs, list) or not all(isinstance(item, str) for item in result_refs):
        raise RuntimeError("grid_submit_answer draft must include result_refs")
    evidence_documents = _verify_evidence_refs(workspace, tuple(claimed))
    result_documents = _verify_result_refs(workspace, tuple(result_refs))
    _verify_result_evidence_links(workspace, tuple(result_refs), result_documents, tuple(claimed), evidence_documents)
    return answer


def _verify_evidence_refs(workspace: RunWorkspace, evidence_refs: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    documents: list[dict[str, Any]] = []
    for evidence_ref in evidence_refs:
        if not evidence_ref.startswith("evidence:sha256:"):
            raise RuntimeError(f"claimed evidence ref is invalid: {evidence_ref}")
        digest = evidence_ref.removeprefix("evidence:sha256:")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(f"claimed evidence ref is invalid: {evidence_ref}")
        document_path = _allowed_evidence_document_path(workspace, digest)
        if document_path is None:
            raise RuntimeError(f"claimed evidence ref is not in the current run: {evidence_ref}")
        document = _load_json_document(document_path)
        _verify_evidence_document(evidence_ref, digest, document_path, document)
        documents.append(document)
    return tuple(documents)


def _allowed_evidence_document_path(workspace: RunWorkspace, digest: str) -> Path | None:
    candidates = (
        workspace.evidence_path / "network-facts" / f"network-fact-{digest}.json",
        workspace.evidence_path / "analysis" / f"analysis-evidence-{digest}.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _load_json_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"claimed evidence document is not UTF-8 JSON: {path.name}") from exc
    except OSError as exc:
        raise RuntimeError(f"claimed evidence document could not be read: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claimed evidence document is not valid JSON: {path.name}") from exc


def _verify_evidence_document(evidence_ref: str, digest: str, path: Path, document: object) -> None:
    if not isinstance(document, dict):
        raise RuntimeError(f"claimed evidence document is malformed: {evidence_ref}")
    if _sha256_canonical_json(document) != digest:
        raise RuntimeError(f"claimed evidence document content does not match reference: {evidence_ref}")
    evidence_type = document.get("evidence_type")
    capability_id = document.get("capability_id")
    if path.parent.name == "network-facts":
        if evidence_type != "network_fact" or capability_id != "topology.branch.endpoints.get":
            raise RuntimeError(f"claimed evidence document type is not allowed: {evidence_ref}")
        return
    allowed_analysis = {
        ("analysis_result", "analysis.powerflow.ac.run"),
        ("contingency_scenario", "analysis.contingency.n_minus_one.run"),
        ("powerflow_non_convergence", "analysis.powerflow.ac.run"),
        ("powerflow_non_convergence", "analysis.contingency.n_minus_one.run"),
    }
    if (str(evidence_type), str(capability_id)) not in allowed_analysis:
        raise RuntimeError(f"claimed evidence document type is not allowed: {evidence_ref}")
    if evidence_type in {"analysis_result", "contingency_scenario"} and not isinstance(document.get("result_ref"), str):
        raise RuntimeError(f"claimed analysis evidence is not linked to a result document: {evidence_ref}")


def _verify_result_refs(workspace: RunWorkspace, result_refs: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for result_ref in result_refs:
        digest = _result_digest(result_ref)
        document_path = _allowed_result_document_path(workspace, digest)
        if document_path is None:
            raise RuntimeError(f"declared result_ref is not in the current run: {result_ref}")
        document = _load_json_document(document_path)
        if not isinstance(document, dict):
            raise RuntimeError(f"declared result document is malformed: {result_ref}")
        if document.get("result_ref") != result_ref:
            raise RuntimeError(f"declared result document reference does not match: {result_ref}")
        body = {key: value for key, value in document.items() if key != "result_ref"}
        if _sha256_canonical_json(body) != digest:
            raise RuntimeError(f"declared result document content does not match reference: {result_ref}")
        if not isinstance(document.get("context_ref"), str) or not isinstance(document.get("revision_ref"), str):
            raise RuntimeError(f"declared result document is missing context references: {result_ref}")
        documents[result_ref] = document
    return documents


def _result_digest(result_ref: str) -> str:
    if not result_ref.startswith("result:sha256:"):
        raise RuntimeError(f"declared result_ref is invalid: {result_ref}")
    digest = result_ref.removeprefix("result:sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError(f"declared result_ref is invalid: {result_ref}")
    return digest


def _allowed_result_document_path(workspace: RunWorkspace, digest: str) -> Path | None:
    candidates = (
        workspace.evidence_path / "results" / f"powerflow-{digest}.json",
        workspace.evidence_path / "results" / f"contingency-{digest}.json",
        workspace.evidence_path / "results" / f"contingency-scenario-{digest}.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _verify_result_evidence_links(
    workspace: RunWorkspace,
    result_refs: tuple[str, ...],
    result_documents: Mapping[str, Mapping[str, Any]],
    claimed_evidence_refs: tuple[str, ...],
    evidence_documents: tuple[Mapping[str, Any], ...],
) -> None:
    """Verify the answer's explicit primary results and evidence-associated results.

    A model declares the result references that directly support its conclusion.  Analysis
    evidence already contains a cryptographic link to its producing result, so requiring the
    model to repeat every one of those links is both redundant and brittle.  We nevertheless
    load and validate every such linked result in the current workspace.
    """
    documents = dict(result_documents)
    declared = set(result_refs)
    linked: set[str] = set()
    claimed = set(claimed_evidence_refs)
    for document in evidence_documents:
        evidence_type = document.get("evidence_type")
        evidence_result_ref = document.get("result_ref")
        if isinstance(evidence_result_ref, str):
            if evidence_type in {"analysis_result", "contingency_scenario"}:
                if evidence_result_ref not in documents:
                    documents.update(_verify_result_refs(workspace, (evidence_result_ref,)))
                _verify_matching_context(evidence_result_ref, documents[evidence_result_ref], document)
                linked.add(evidence_result_ref)

    for result_ref, result_document in documents.items():
        result_evidence_refs = result_document.get("evidence_refs")
        if isinstance(result_evidence_refs, list) and any(ref in claimed for ref in result_evidence_refs):
            linked.add(result_ref)

    for result_ref in result_refs:
        if result_ref not in linked:
            raise RuntimeError(f"declared result_ref is not linked to claimed evidence: {result_ref}")


def _verify_matching_context(result_ref: str, result_document: Mapping[str, Any], evidence_document: Mapping[str, Any]) -> None:
    if (
        evidence_document.get("context_ref") != result_document.get("context_ref")
        or evidence_document.get("revision_ref") != result_document.get("revision_ref")
    ):
        raise RuntimeError(f"declared result_ref context does not match claimed evidence: {result_ref}")


def _sha256_canonical_json(document: object) -> str:
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_child_with_live_stderr(
    command: Sequence[str], cwd: Path, on_stderr_line: Callable[[str], None]
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    stderr_lines: list[str] = []
    from threading import Thread

    def forward_stderr() -> None:
        for line in process.stderr:
            stderr_lines.append(line)
            on_stderr_line(line.rstrip("\r\n"))

    thread = Thread(target=forward_stderr, daemon=True)
    thread.start()
    stdout = process.stdout.read()
    returncode = process.wait()
    thread.join()
    return subprocess.CompletedProcess(list(command), returncode, stdout, "".join(stderr_lines))


@app.command()
def report(
    questions: Path = typer.Option(_repo_root() / "validation/questions/task.md.txt", "--questions", exists=True, readable=True),
    output: Path | None = typer.Option(None, "--output", help="Optional JSONL file containing only answer envelopes."),
    report_path: Path | None = typer.Option(None, "--report-path", help="Markdown report destination."),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Run a question file sequentially and write a readable simulation-analysis report."""
    project_paths = ProjectPaths.from_root(Path.cwd())
    runtime_env = _runtime_environment(project_paths.root)
    resolved = resolve_llm(
        catalog=ProviderCatalog.load(),
        cli=CliLLMOptions(provider=provider, model=model),
        environ=runtime_env,
        env_file=project_paths.root / ".env",
        oauth_configured=lambda profile: ProjectAuthStore(project_paths.state_dir / "auth").status(profile).configured,
    ).config
    batch_id = f"batch-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    records: list[BatchRecord] = []
    typer.echo(f"开始批量系统仿真分析 batch={batch_id} 问题文件={questions}")
    for ordinal, question in enumerate(load_questions(questions), start=1):
        question_id = f"{batch_id}-q{ordinal:03d}"
        typer.echo(f"\n[{ordinal}] 开始：{question}")
        command = ["grid-agent", "run", "--question-id", question_id]
        command.extend(["--provider", resolved.provider, "--model", resolved.model])
        command.append(question)
        started = time.monotonic()
        completed = _run_child_with_live_stderr(command, project_paths.root, lambda line: typer.echo(line, err=True))
        duration = time.monotonic() - started
        try:
            payload = json.loads(completed.stdout)
            envelope = AnswerEnvelope.model_validate(payload)
            answer = envelope.answer_output
            returned_id = envelope.question_id
        except Exception:
            answer = "执行限制 / execution limitation: invalid batch child output"
            returned_id = question_id
        run_path = project_paths.runs_dir / returned_id
        observation = read_run_observations(run_path)
        status = "success" if completed.returncode == 0 else "failed"
        error = None if status == "success" else _summary(completed.stderr or completed.stdout)
        records.append(BatchRecord(ordinal, question, returned_id, answer, status, duration, str(run_path) if run_path.exists() else None, observation, error))
        typer.echo(f"[{ordinal}] {'完成' if status == 'success' else '失败'}：{duration:.2f}s；工具步骤 {len(observation.steps)}；证据 {len(observation.evidence_sources)}")
    destination = report_path or project_paths.runs_dir / "reports" / f"{batch_id}-系统仿真分析报告.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        "执行时间（UTC）": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "LLM Provider": resolved.provider,
        "LLM 模型": resolved.model,
        "单次请求时限": f"{resolved.timeout_seconds:g} 秒",
        "SDK 自动重试": f"{resolved.max_retries} 次",
        "仿真器边界": "pandapower 3.4.0（经 gridctl）",
        "gridctl": str(GridctlLocator(_repo_root()).resolve()),
    }
    destination.write_text(render_markdown(batch_id=batch_id, source_name=str(questions), environment=environment, records=records), encoding="utf-8")
    if output:
        write_jsonl(output, records)
    typer.echo(f"\n报告已写入：{destination}")
    if output:
        typer.echo(f"标准结果 JSONL 已写入：{output}")
    if any(record.status == "failed" for record in records):
        raise typer.Exit(1)


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
            diagnostic_plan = plan_diagnostic(request.question)
            if isinstance(diagnostic_plan, str):
                answer = diagnostic_plan
            else:
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
