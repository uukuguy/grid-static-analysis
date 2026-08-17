from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from pathlib import Path

import typer
from dotenv import dotenv_values

from grid_agent.analysis.capabilities import CapabilityContextCatalog
from grid_agent.analysis.integrity import ContentReferenceVerifier, ReferenceDiagnostic
from grid_agent.analysis.projector import AnalysisContextProjector
from grid_agent.analysis.runner import AnalysisOutcome, AnalysisRequest, AnalysisRunner
from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.analysis.turns import TurnController
from grid_agent.analysis.workspace import AnalysisWorkspace
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
from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.capture import NativeCaptureAdapter
from grid_agent.trajectory.context_bridge import NativeContextBridge
from grid_agent.trajectory.events import RunEvent
from grid_agent.trajectory.recorder import RunEventRecorder
from grid_agent.trajectory.api.server import serve_trajectory
from grid_agent.reporting import AuditDiagnostic, humanize_answer, load_questions


app = typer.Typer(add_completion=False)
trajectory_app = typer.Typer(help="Inspect read-only agent and business trajectories.")
app.add_typer(trajectory_app, name="trajectory")
_NON_SIMULATOR_CAPABILITIES = {"grid_submit_answer", "grid_guide_open"}


@dataclass(frozen=True, slots=True)
class SubmittedAnswer:
    answer_output: str
    diagnostics: tuple[AuditDiagnostic, ...]


@trajectory_app.command("serve")
def trajectory_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port", min=1, max=65535),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    """Serve immutable trajectory projections only on loopback interfaces."""
    try:
        serve_trajectory(
            project_paths=ProjectPaths.from_root(Path.cwd()),
            host=host,
            port=port,
            runs_root=runs_root,
        )
    except Exception as exc:
        typer.echo(f"grid-agent trajectory error: {exc}", err=True)
        raise typer.Exit(1) from exc


class _TrajectoryAllowedRefs:
    """Publish the controller-known, non-artifact refs visible to native tools."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._refs: set[str] = set()
        self._write(self._refs)

    def observe(self, event: RunEvent) -> None:
        candidates = {
            reference
            for reference in (
                *event.refs.consumed,
                *event.refs.produced,
                *event.refs.evidence,
            )
            if not reference.startswith("artifact:")
        }
        updated = self._refs | candidates
        if updated == self._refs:
            return
        self._write(updated)
        self._refs = updated

    def _write(self, references: set[str]) -> None:
        payload = json.dumps(
            {
                "schema_version": "grid-trajectory-allowed-refs/1.0",
                "refs": sorted(references),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _install_gridctl(workspace: RunWorkspace | AnalysisWorkspace) -> None:
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


def _admit_successful_tool_references(workspace: RunWorkspace, event: Mapping[str, Any]) -> None:
    details = _tool_result_details(event)
    if not isinstance(details, Mapping):
        return
    capability = details.get("capability")
    if not isinstance(capability, str) or capability in _NON_SIMULATOR_CAPABILITIES:
        return
    ok = details.get("ok")
    if ok is not True and ok is not False:
        ok = event.get("isError") is not True
    if ok is not True:
        return
    result = details.get("result", {})
    if not isinstance(result, Mapping):
        result = {}
    evidence_refs = details.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        evidence_refs = []
    ContentReferenceVerifier(workspace.root_path).admit_successful_tool_references(
        capability,
        result,
        tuple(reference for reference in evidence_refs if isinstance(reference, str)),
    )


def _tool_result_details(event: Mapping[str, Any]) -> object:
    if event.get("type") == "tool_result":
        return event
    if event.get("type") != "tool_execution_end":
        return None
    result = event.get("result")
    if isinstance(result, Mapping):
        details = result.get("details")
        if isinstance(details, Mapping):
            return details
        return result
    details = event.get("details")
    if isinstance(details, Mapping):
        return details
    return None


def _load_verified_answer_draft(workspace: RunWorkspace) -> str:
    draft_path = workspace.root_path / "answer-draft.json"
    if not draft_path.is_file():
        raise RuntimeError("grid_submit_answer did not create an answer draft")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    return humanize_answer(answer)


def _load_submitted_answer(workspace: RunWorkspace) -> SubmittedAnswer:
    draft_path = workspace.root_path / "answer-draft.json"
    if not draft_path.is_file():
        raise RuntimeError("grid_submit_answer did not create an answer draft")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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

    diagnostics = _audit_answer_draft(workspace, tuple(claimed), tuple(result_refs))
    _write_answer_audit(workspace, diagnostics)
    return SubmittedAnswer(answer_output=answer, diagnostics=diagnostics)


def _audit_answer_draft(
    workspace: RunWorkspace,
    claimed_evidence_refs: tuple[str, ...],
    result_refs: tuple[str, ...],
) -> tuple[AuditDiagnostic, ...]:
    diagnostics = ContentReferenceVerifier(workspace.root_path).audit_answer_references(
        claimed_evidence_refs,
        result_refs,
    )
    return tuple(_audit_diagnostic(diagnostic) for diagnostic in diagnostics)


def _audit_diagnostic(diagnostic: ReferenceDiagnostic) -> AuditDiagnostic:
    return AuditDiagnostic(
        severity=diagnostic.severity,
        finding=diagnostic.message,
        impact=diagnostic.impact,
        remediation=diagnostic.remediation,
    )


def _write_answer_audit(workspace: RunWorkspace, diagnostics: tuple[AuditDiagnostic, ...]) -> None:
    audit_path = workspace.root_path / "answer-audit.json"
    temporary = audit_path.with_name(f".{audit_path.name}.tmp")
    payload = {
        "diagnostics": [
            {
                "severity": diagnostic.severity,
                "finding": diagnostic.finding,
                "impact": diagnostic.impact,
                "remediation": diagnostic.remediation,
            }
            for diagnostic in diagnostics
        ]
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(audit_path)


def _verify_evidence_refs(workspace: RunWorkspace, evidence_refs: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    verifier = ContentReferenceVerifier(workspace.root_path)
    return tuple(dict(verifier.verify_evidence(evidence_ref).document) for evidence_ref in evidence_refs)


def _verify_result_refs(workspace: RunWorkspace, result_refs: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    verifier = ContentReferenceVerifier(workspace.root_path)
    return {result_ref: dict(verifier.verify_result(result_ref).document) for result_ref in result_refs}


def _verify_result_evidence_links(
    workspace: RunWorkspace,
    result_refs: tuple[str, ...],
    result_documents: Mapping[str, Mapping[str, Any]],
    claimed_evidence_refs: tuple[str, ...],
    evidence_documents: tuple[Mapping[str, Any], ...],
) -> None:
    ContentReferenceVerifier(workspace.root_path)._verify_result_evidence_links(
        result_refs,
        result_documents,
        claimed_evidence_refs,
        evidence_documents,
    )


def _resolve_artifact_root(project_root: Path, artifact_root: Path | None) -> Path:
    root = artifact_root or project_root / "runs"
    resolved = (project_root / root if not root.is_absolute() else root).resolve()
    if not resolved.is_relative_to(project_root):
        raise ValueError(f"artifact root must be under project root: {resolved}")
    return resolved


def _project_relative(path: Path, project_root: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(project_root):
        raise ValueError(f"analysis report path is outside project root: {resolved}")
    return resolved.relative_to(project_root).as_posix()


def _runtime_record(
    resolved_provider: str,
    resolved_model: str,
    environment_description: Mapping[str, Any],
) -> dict[str, Any]:
    raw_families = environment_description.get("capability_families", [])
    capability_families = [dict(item) for item in raw_families if isinstance(item, Mapping)]
    return {
        "provider": resolved_provider,
        "model": resolved_model,
        "grid_capability_protocol": str(environment_description.get("protocol_version", "1.0")),
        "pandapower_version": str(environment_description.get("pandapower_version", "3.4.0")),
        "capability_families": capability_families,
    }


def _input_record(copied_instructions: Any) -> dict[str, str | int]:
    return {
        "source_path": copied_instructions.source_path,
        "copied_path": copied_instructions.copied_path,
        "sha256": copied_instructions.sha256,
        "instruction_count": copied_instructions.instruction_count,
    }


def _analysis_report_envelope(outcome: AnalysisOutcome, project_root: Path) -> AnswerEnvelope:
    if outcome.status == "completed":
        answer_output = _project_relative(outcome.report_path, project_root)
    else:
        answer_output = f"分析未完成；部分报告已保存：{_project_relative(outcome.report_path, project_root)}"
    return AnswerEnvelope(question_id=outcome.analysis_id, answer_output=answer_output)


def _emit_analysis_outcome(outcome: AnalysisOutcome, project_root: Path) -> None:
    envelope = _analysis_report_envelope(outcome, project_root)
    typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
    if outcome.status != "completed":
        raise typer.Exit(1)


def _execute_analysis(
    *,
    instructions: Path,
    artifact_root: Path | None,
    provider: str | None,
    model: str | None,
) -> AnalysisOutcome:
    project_paths = ProjectPaths.from_root(Path.cwd())
    root = _resolve_artifact_root(project_paths.root, artifact_root)
    workspace = AnalysisWorkspace.create(root)
    copied_instructions = workspace.copy_instructions(instructions)
    instruction_items = load_questions(instructions)
    runtime_env = _runtime_environment(project_paths.root)
    auth_store = ProjectAuthStore.from_pi_agent_dir(project_paths.pi_agent_dir)
    resolved = resolve_llm(
        catalog=ProviderCatalog.load(),
        cli=CliLLMOptions(provider=provider, model=model),
        environ=runtime_env,
        env_file=project_paths.root / ".env",
        oauth_configured=lambda profile: auth_store.status(profile).configured,
    )
    runtime_lock = PiRuntimeLock.load(project_paths.runtime_lock)
    command = PiRuntimeLocator(project_paths.pi_runtime_dir, runtime_env, runtime_lock=runtime_lock).resolve(require_managed=True)
    _install_gridctl(workspace)
    gridctl = GridctlClient(
        executable=workspace.bin_path / "gridctl",
        workspace=workspace.root_path,
        timeout_seconds=60,
    )
    environment_description = gridctl.invoke("environment.describe", {})
    capability_documents = load_packaged_capability_documents(_repo_root())
    tool_catalog_path = ToolCatalog.from_environment(
        capability_documents,
        environment_description,
    ).materialize(workspace.root_path / "tool-catalog.json")
    guide_index_path = GuideIndex.load(_repo_root() / "skills/grid-static-analysis").materialize(
        workspace.root_path / "guide-index.json"
    )
    PiConfigMaterializer(project_paths.pi_agent_dir).materialize(resolved)
    secret_values = (
        {resolved.secret.value} if resolved.secret is not None else set()
    )
    artifacts = ImmutableArtifactRegistry(workspace.root_path)
    allowed_refs_path = (
        workspace.root_path / "context" / "trajectory-allowed-refs.json"
    )
    allowed_refs = _TrajectoryAllowedRefs(allowed_refs_path)
    recorder = RunEventRecorder(
        workspace.events_path,
        workspace.analysis_id,
        artifact_registry=artifacts,
        secret_values=secret_values,
        subscribers=(allowed_refs.observe,),
    )
    try:
        bridge = NativeContextBridge(recorder, artifacts, workspace)
        store = AnalysisContextStore.initialize(
            workspace,
            input_record=_input_record(copied_instructions),
            runtime_record=_runtime_record(
                resolved.config.provider,
                resolved.config.model,
                environment_description,
            ),
            transition_commit=bridge.commit,
        )
        capture = NativeCaptureAdapter(
            recorder,
            artifacts,
            workspace,
            acknowledgements_path=project_paths.trajectory_acks_path(
                workspace.analysis_id
            ),
        )
        launch = build_pi_launch(
            resolved,
            RuntimePaths(
                command=command,
                project_pi_dir=project_paths.pi_agent_dir,
                session_dir=workspace.pi_path,
                workspace=workspace.root_path,
                gridctl_dir=workspace.bin_path,
                extension_path=_repo_root() / "packages/pi-grid-tools/src/domain-tools.mjs",
                tool_catalog_path=tool_catalog_path,
                guide_index_path=guide_index_path,
                answer_draft_path=workspace.active_answer_draft_path,
                system_policy_path=_repo_root() / "configs/agent/system-policy.md",
                active_turn_path=workspace.active_turn_path,
                analysis_context_view_path=workspace.context_view_path,
                trajectory_requests_path=workspace.requests_path,
                trajectory_capture_state_path=workspace.trajectory_capture_state_path,
                trajectory_allowed_refs_path=allowed_refs_path,
                trajectory_acks_path=project_paths.trajectory_acks_path(
                    workspace.analysis_id
                ),
            ),
            base_environment=runtime_env,
        )
        verifier = ContentReferenceVerifier(workspace.root_path)
        trace = JsonlTraceWriter(
            workspace.trace_path,
            secret_values=secret_values,
        )
        progress = _ProgressReporter("\n".join(instruction_items))
        typer.echo(
            f"开始连续系统仿真分析 analysis={workspace.analysis_id} 指令文件={instructions} "
            f"provider={resolved.config.provider} model={resolved.config.model}",
            err=True,
        )
        runner = AnalysisRunner(
            workspace=workspace,
            store=store,
            turn_controller=TurnController(
                workspace,
                store,
                audit_callback=lambda claimed, results: verifier.audit_answer_references(claimed, results),
                recorder=recorder,
            ),
            pi_client=PiRpcClient(launch, workspace, trace),
            projector=AnalysisContextProjector(
                store,
                verifier,
                CapabilityContextCatalog.from_documents(capability_documents),
            ),
            environment={
                "provider": resolved.config.provider,
                "model": resolved.config.model,
                "pandapower": str(environment_description.get("pandapower_version", "3.4.0")),
                "gridctl": str(workspace.bin_path / "gridctl"),
            },
            progress_callback=progress.on_event,
            trace=trace,
            capture=capture,
            context_bridge=bridge,
        )
        outcome = runner.run(
            AnalysisRequest(
                analysis_id=workspace.analysis_id,
                instructions=instruction_items,
            )
        )
        typer.echo(
            f"连续分析结束 analysis={outcome.analysis_id} status={outcome.status} "
            f"completed={outcome.completed_turns}/{outcome.total_turns} report={_project_relative(outcome.report_path, project_paths.root)}",
            err=True,
        )
        return outcome
    finally:
        recorder.close()


@app.command()
def analysis(
    instructions: Path = typer.Option(_repo_root() / "validation/questions/task.md.txt", "--instructions", exists=True, readable=True),
    artifact_root: Path | None = typer.Option(None, "--artifact-root"),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Run an ordered instruction file as one continuous static-analysis session."""
    project_root = ProjectPaths.from_root(Path.cwd()).root
    try:
        outcome = _execute_analysis(
            instructions=instructions,
            artifact_root=artifact_root,
            provider=provider,
            model=model,
        )
    except Exception as exc:
        typer.echo(f"grid-agent error: {exc}", err=True)
        envelope = AnswerEnvelope(
            question_id="analysis-error",
            answer_output=f"执行限制 / execution limitation: {type(exc).__name__}",
        )
        typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
        raise typer.Exit(1)
    _emit_analysis_outcome(outcome, project_root)


@app.command()
def report(
    questions: Path = typer.Option(_repo_root() / "validation/questions/task.md.txt", "--questions", exists=True, readable=True),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
) -> None:
    """Compatibility alias for ``analysis --instructions``."""
    project_root = ProjectPaths.from_root(Path.cwd()).root
    try:
        outcome = _execute_analysis(
            instructions=questions,
            artifact_root=None,
            provider=provider,
            model=model,
        )
    except Exception as exc:
        typer.echo(f"grid-agent error: {exc}", err=True)
        envelope = AnswerEnvelope(
            question_id="analysis-error",
            answer_output=f"执行限制 / execution limitation: {type(exc).__name__}",
        )
        typer.echo(json.dumps(envelope.model_dump(), ensure_ascii=False))
        raise typer.Exit(1)
    _emit_analysis_outcome(outcome, project_root)


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
            command = PiRuntimeLocator(project_paths.pi_runtime_dir, runtime_environment, runtime_lock=runtime_lock).resolve(require_managed=True)
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
                def on_pi_event(event: dict[str, Any]) -> None:
                    _admit_successful_tool_references(workspace, event)
                    progress.on_event(event)

                rpc.prompt_and_wait(
                    request.question,
                    on_event=on_pi_event,
                    on_heartbeat=progress.heartbeat,
                    require_answer_text=False,
                )
                submitted = _load_submitted_answer(workspace)
            finally:
                rpc.stop()
            answer = submitted.answer_output
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
