from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal



@dataclass(frozen=True)
class SimulationContext:
    """Immutable, structured network state actually opened for one question."""

    context_ref: str
    model: str
    source: str
    engine: str
    engine_version: str
    semantic_sha256: str | None
    counts: Mapping[str, int]
    absolute_path: str | None = None


@dataclass(frozen=True)
class AnalysisStep:
    capability: str
    duration_seconds: float
    summary: str
    ok: bool


@dataclass(frozen=True)
class EvidenceSource:
    reference: str
    description: str
    capability: str
    result_ref: str | None
    relative_path: str | None
    absolute_path: str | None = None


@dataclass(frozen=True)
class RunObservation:
    context: SimulationContext | None
    steps: tuple[AnalysisStep, ...]
    evidence_sources: tuple[EvidenceSource, ...]
    result_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditDiagnostic:
    severity: Literal["warning", "error"]
    finding: str
    impact: str
    remediation: str


@dataclass(frozen=True)
class BatchRecord:
    ordinal: int
    question: str
    question_id: str
    answer_output: str
    status: str
    duration_seconds: float
    run_path: str | None
    observation: RunObservation
    error: str | None
    draft_answer: str | None = None
    audit_diagnostics: tuple[AuditDiagnostic, ...] = ()


_ACTION_LABELS = {
    "environment.describe": "核对仿真器协议和已发布能力",
    "model.list": "确认可用的已注册网络模型",
    "context.open": "打开只读网络仿真环境上下文",
    "context.get": "读取已打开的仿真环境上下文",
    "model.element.get": "定位问题涉及的网络元件",
    "model.dataset.describe": "核对可查询的数据集与字段",
    "model.dataset.query": "查询网络模型数据",
    "topology.branch.endpoints.get": "核查支路两端母线",
    "topology.components.get": "核查网络拓扑连通性",
    "analysis.powerflow.ac.run": "运行交流潮流计算",
    "result.branches.rank": "按支路运行指标筛选和排序",
    "analysis.contingency.n_minus_one.run": "执行单支路 N-1 静态安全校核",
    "evidence.get": "读取已持久化的仿真证据",
    "grid_guide_open": "读取已发布的领域操作指南",
    "grid_submit_answer": "提交带结构化证据的最终答案",
}

_TOOL_TO_CAPABILITY = {
    "grid_environment_describe": "environment.describe",
    "grid_model_list": "model.list",
    "grid_context_open": "context.open",
    "grid_context_get": "context.get",
    "grid_model_element_get": "model.element.get",
    "grid_model_dataset_describe": "model.dataset.describe",
    "grid_model_dataset_query": "model.dataset.query",
    "grid_topology_branch_endpoints": "topology.branch.endpoints.get",
    "grid_topology_components": "topology.components.get",
    "grid_analysis_powerflow_ac": "analysis.powerflow.ac.run",
    "grid_result_branches_rank": "result.branches.rank",
    "grid_analysis_contingency_n_minus_one": "analysis.contingency.n_minus_one.run",
    "grid_evidence_get": "evidence.get",
    "grid_guide_open": "grid_guide_open",
    "grid_submit_answer": "grid_submit_answer",
}

_OPAQUE_REFERENCE = re.compile(
    r"\b(?:context|revision|result|evidence):sha256:[0-9a-f]{64}\b|"
    r"\basset:[a-z0-9_-]+:sha256:[0-9a-f]{64}\b"
)


def humanize_answer(value: str) -> str:
    """Remove opaque internal identifiers from operator-facing answer prose.

    The original structured references remain in the run's answer draft and
    evidence artifacts; reports link to those artifacts instead of presenting
    hashes as if they were explanatory evidence.
    """
    without_parenthetical_refs = re.sub(
        rf"[（(]\s*(?:{_OPAQUE_REFERENCE.pattern})\s*[）)]", "", value
    )
    cleaned = _OPAQUE_REFERENCE.sub("", without_parenthetical_refs)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"，\s*，", "，", cleaned)
    return cleaned.strip()


def load_questions(path: Path) -> tuple[str, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    questions = tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    if not questions:
        raise ValueError(f"question file contains no questions: {path}")
    return questions


def render_markdown(*, batch_id: str, source_name: str, environment: Mapping[str, str], records: Sequence[BatchRecord]) -> str:
    counts = {status: sum(record.status == status for record in records) for status in ("success", "limited", "failed")}
    lines = [
        "# 系统仿真分析报告",
        "",
        f"- 批次编号：`{batch_id}`",
        f"- 问题文件：`{source_name}`",
        f"- 总问题数：{len(records)}；成功：{counts['success']}；受限：{counts['limited']}；失败：{counts['failed']}",
        "",
        "## 本批次运行环境",
        "",
    ]
    lines.extend(f"- {label}：`{value}`" for label, value in environment.items())
    for record in records:
        lines.extend(["", f"## {record.ordinal}. {record.question}", "", "### 回答", "", _display_answer(record), ""])
        lines.extend(
            [
                "### 执行信息",
                "",
                f"- question_id：`{record.question_id}`",
                f"- 状态：{_status_label(record.status)}",
                f"- 总时长：{record.duration_seconds:.2f} 秒",
                f"- 运行目录：{_link(record.run_path, '打开本题运行目录')}" if record.run_path else "- 运行目录：未创建（离线知识或启动前失败）",
                "",
                "### 仿真环境上下文",
                "",
            ]
        )
        _render_context(lines, record.observation.context)
        lines.extend(["", "### 实际分析过程", ""])
        if record.observation.steps:
            for index, step in enumerate(record.observation.steps, start=1):
                state = "完成" if step.ok else "返回受限/错误"
                lines.append(f"{index}. {step.summary}（`{step.capability}`，{state}，{step.duration_seconds:.2f} 秒）")
        else:
            lines.append("未观察到已完成的领域工具调用。")
        lines.extend(["", "### 证据来源", ""])
        _render_evidence(lines, record.observation)
        if record.audit_diagnostics:
            lines.extend(["", "### 审计结论", ""])
            for diagnostic in record.audit_diagnostics:
                lines.extend(
                    [
                        f"- 严重性：{diagnostic.severity}",
                        f"- 发现：{diagnostic.finding}",
                        f"- 影响：{diagnostic.impact}",
                        f"- 建议：{diagnostic.remediation}",
                    ]
                )
        if record.error:
            lines.extend(
                [
                    "",
                    "### 审计结论",
                    "",
                    f"- 发现：{record.error}",
                    "- 影响：该草稿不能作为最终提交结果；已完成的工具调用和工件仍保留，供复核和重跑使用。",
                    "- 建议：打开本题运行目录中的 `answer-draft.json` 与证据工件，核对答案主张是否能由当前运行的证据直接支持，然后重跑该题。",
                ]
            )
            if record.draft_answer:
                lines.extend(["", "### 模型草稿（未采纳）", "", humanize_answer(record.draft_answer)])
    return "\n".join(lines) + "\n"


def write_jsonl(path: Path, records: Sequence[BatchRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"question_id": record.question_id, "answer_output": record.answer_output}, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def append_jsonl_record(path: Path, record: BatchRecord) -> None:
    """Durably expose one completed envelope without waiting for the batch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"question_id": record.question_id, "answer_output": record.answer_output}, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def read_answer_audit(run_path: Path) -> tuple[AuditDiagnostic, ...]:
    """Read a child-run audit without allowing malformed diagnostics to break reports."""
    audit_path = run_path / "answer-audit.json"
    if not audit_path.is_file():
        return ()
    try:
        document = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return (_malformed_answer_audit(),)
    if not isinstance(document, Mapping):
        return (_malformed_answer_audit(),)
    diagnostics = document.get("diagnostics")
    if not isinstance(diagnostics, list):
        return (_malformed_answer_audit(),)

    parsed: list[AuditDiagnostic] = []
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            return (_malformed_answer_audit(),)
        severity = diagnostic.get("severity")
        finding = diagnostic.get("finding")
        impact = diagnostic.get("impact")
        remediation = diagnostic.get("remediation")
        if (
            severity not in {"warning", "error"}
            or not isinstance(finding, str)
            or not isinstance(impact, str)
            or not isinstance(remediation, str)
        ):
            return (_malformed_answer_audit(),)
        parsed.append(AuditDiagnostic(severity, finding, impact, remediation))
    return tuple(parsed)


def _malformed_answer_audit() -> AuditDiagnostic:
    return AuditDiagnostic(
        severity="error",
        finding="answer-audit.json is malformed.",
        impact="The answer audit could not be displayed reliably in this report.",
        remediation="Inspect and regenerate the child run's answer-audit.json file.",
    )


def read_run_observations(run_path: Path) -> RunObservation:
    events_path = run_path / "events.jsonl"
    if not events_path.is_file():
        return RunObservation(None, (), (), ())
    events = [_json_line(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    starts: dict[str, list[str]] = {}
    steps: list[AnalysisStep] = []
    context: SimulationContext | None = None
    result_refs: list[str] = []
    evidence_refs: list[str] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        payload = _payload(event)
        if not isinstance(payload, Mapping):
            continue
        event_type = payload.get("type", payload.get("event"))
        if event_type == "tool_execution_start":
            tool_name = payload.get("toolName")
            if isinstance(tool_name, str):
                starts.setdefault(_TOOL_TO_CAPABILITY.get(tool_name, tool_name), []).append(str(event.get("timestamp", "")))
            continue
        if event_type != "tool_result" or not isinstance(payload.get("capability"), str):
            continue
        capability = str(payload["capability"])
        start = starts.get(capability, []).pop(0) if starts.get(capability) else ""
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
        ok = payload.get("ok") is True
        steps.append(AnalysisStep(capability, _seconds_between(start, str(event.get("timestamp", ""))), _step_summary(capability, result), ok))
        if capability == "context.open" and ok:
            context = _simulation_context(result)
        _add_refs(payload.get("evidence_refs"), evidence_refs)
        _add_refs(result.get("evidence_refs"), evidence_refs)
        _add_refs([result.get("evidence_ref")], evidence_refs)
        _add_refs([result.get("result_ref")], result_refs)
        _add_refs(result.get("result_refs"), result_refs)
    if context is not None:
        digest = context.context_ref.removeprefix("context:sha256:")
        snapshot = run_path / "evidence" / "contexts" / f"context-{digest}.json"
        if snapshot.is_file():
            context = replace(context, absolute_path=str(snapshot))
    evidence_sources = tuple(_describe_evidence(run_path, reference) for reference in dict.fromkeys(evidence_refs))
    return RunObservation(context, tuple(steps), evidence_sources, tuple(dict.fromkeys(result_refs)))


def _render_context(lines: list[str], context: SimulationContext | None) -> None:
    if context is None:
        lines.append("本题未打开网络模型上下文；回答基于领域规范或在启动前受限，未把它表述为仿真结论。")
        return
    counts = "，".join(f"{key} {value}" for key, value in context.counts.items()) or "未返回元件统计"
    lines.extend(
        [
            f"- 网络模型：`{context.model}`；来源：`{context.source}`",
            f"- 仿真器：`{context.engine} {context.engine_version}`；模型规模：{counts}",
            "- 上下文状态：只读、冻结；本题所有网络查询、潮流和 N-1（如有）均以此快照为边界。",
            f"- {_link(context.absolute_path, '查看冻结上下文快照')}（包含模型版本和仿真器元数据）。",
        ]
    )


def _render_evidence(lines: list[str], observation: RunObservation) -> None:
    if observation.evidence_sources:
        sources = _representative_evidence(observation.evidence_sources)
        for source in sources:
            location = _link(source.absolute_path, "查看证据工件") if source.absolute_path else "证据工件不可用"
            lines.append(f"- {source.description}（由 `{source.capability}` 产生；{location}）")
        omitted = len(observation.evidence_sources) - len(sources)
        if omitted:
            lines.append(f"- 其余 {omitted} 个场景证据已保存在本题运行目录；主报告仅列出最具代表性的结果，避免用重复条目掩盖风险结论。")
    elif observation.result_refs:
        lines.append(f"- 已产生 {len(observation.result_refs)} 份仿真结果工件，但本题未提交可展示的单独证据引用；请在本题运行目录复核。")
    else:
        lines.append("本题没有可引用的仿真证据；报告不把知识性说明伪装为计算结果。")


def _simulation_context(result: Mapping[str, Any]) -> SimulationContext | None:
    required = ("context_ref", "model", "source", "engine", "pandapower_version")
    if not all(isinstance(result.get(key), str) for key in required):
        return None
    counts = result.get("counts")
    normalized_counts = {str(key): int(value) for key, value in counts.items() if isinstance(value, int)} if isinstance(counts, Mapping) else {}
    semantic = result.get("semantic_sha256")
    return SimulationContext(str(result["context_ref"]), str(result["model"]), str(result["source"]), str(result["engine"]), str(result["pandapower_version"]), str(semantic) if isinstance(semantic, str) else None, normalized_counts)


def _step_summary(capability: str, result: Mapping[str, Any]) -> str:
    label = _ACTION_LABELS.get(capability, "调用已发布的领域能力")
    if capability == "context.open":
        model = result.get("model")
        return f"{label}{f'：{model}' if isinstance(model, str) else ''}"
    if capability == "analysis.powerflow.ac.run":
        loss = result.get("total_active_loss")
        if isinstance(loss, Mapping) and isinstance(loss.get("value"), (int, float)):
            return f"{label}：收敛，计算有功网损 {loss['value']:.4f} {loss.get('unit', 'MW')}"
    if capability == "analysis.contingency.n_minus_one.run":
        scenarios = result.get("scenarios")
        if isinstance(scenarios, list):
            return f"{label}：完成 {len(scenarios)} 个故障场景"
    if capability == "topology.branch.endpoints.get":
        endpoints = result.get("endpoints")
        if isinstance(endpoints, Mapping):
            return f"{label}：已返回线路端点和可追溯网络事实"
    return label


def _describe_evidence(run_path: Path, reference: str) -> EvidenceSource:
    digest = reference.removeprefix("evidence:sha256:")
    candidates = (
        run_path / "evidence" / "network-facts" / f"network-fact-{digest}.json",
        run_path / "evidence" / "analysis" / f"analysis-evidence-{digest}.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return EvidenceSource(reference, "当前运行中记录的证据引用（文件未找到）", "unknown", None, None)
    document = _load_document(path)
    if not isinstance(document, Mapping):
        return EvidenceSource(reference, "当前运行中记录的证据引用（内容不可读）", "unknown", None, str(path.relative_to(run_path)), str(path))
    capability = str(document.get("capability_id", "unknown"))
    result_ref = document.get("result_ref") if isinstance(document.get("result_ref"), str) else None
    return EvidenceSource(reference, _evidence_description(document), capability, result_ref, str(path.relative_to(run_path)), str(path))


def _evidence_description(document: Mapping[str, Any]) -> str:
    evidence_type = document.get("evidence_type")
    facts = document.get("facts") if isinstance(document.get("facts"), Mapping) else {}
    if evidence_type == "network_fact":
        return "网络拓扑事实：已持久化该支路两端母线的来源记录"
    if evidence_type == "analysis_result":
        loss = facts.get("total_active_loss")
        if isinstance(loss, Mapping) and isinstance(loss.get("value"), (int, float)):
            return f"交流潮流证据：已收敛，有功网损 {loss['value']:.4f} {loss.get('unit', 'MW')}"
        return "交流潮流证据：已持久化计算结果"
    if evidence_type == "contingency_scenario":
        loading = facts.get("max_loading_percent")
        violations = facts.get("violation_count")
        parts = ["N-1 场景证据"]
        if isinstance(loading, (int, float)):
            parts.append(f"最大负载率 {loading:.2f}%")
        if isinstance(violations, int):
            parts.append(f"越限 {violations} 项")
        return "：".join([parts[0], "，".join(parts[1:])]) if len(parts) > 1 else parts[0]
    return "当前运行中持久化的仿真证据"


def _load_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _payload(event: Mapping[str, Any]) -> object:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else event


def _json_line(line: str) -> object:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _add_refs(value: object, destination: list[str]) -> None:
    if isinstance(value, list):
        destination.extend(item for item in value if isinstance(item, str))


def _seconds_between(start: str, end: str) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        return 0.0


def _link(path: str | None, label: str) -> str:
    return f"[{label}]({path})" if path and Path(path).is_absolute() else label


def _representative_evidence(sources: Sequence[EvidenceSource]) -> tuple[EvidenceSource, ...]:
    """Keep direct evidence plus the most stressed N-1 cases readable."""
    scenarios = [source for source in sources if source.capability == "analysis.contingency.n_minus_one.run"]
    direct = [source for source in sources if source.capability != "analysis.contingency.n_minus_one.run"]

    def loading(source: EvidenceSource) -> float:
        matched = re.search(r"最大负载率 ([0-9.]+)%", source.description)
        return float(matched.group(1)) if matched else -1.0

    return tuple(direct + sorted(scenarios, key=loading, reverse=True)[:3])


def _display_answer(record: BatchRecord) -> str:
    if record.status == "failed" and record.draft_answer:
        return "本题未形成可验收的最终回答。下方保留模型草稿及审计说明，便于判断问题所在。"
    return record.answer_output


def _status_label(status: str) -> str:
    return {"success": "成功", "limited": "受限", "failed": "失败"}.get(status, status)
