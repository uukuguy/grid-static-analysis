from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class RunObservation:
    context: SimulationContext | None
    steps: tuple[AnalysisStep, ...]
    evidence_sources: tuple[EvidenceSource, ...]
    result_refs: tuple[str, ...]


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
        lines.extend(["", f"## {record.ordinal}. {record.question}", "", "### 回答", "", record.answer_output, ""])
        lines.extend(
            [
                "### 执行信息",
                "",
                f"- question_id：`{record.question_id}`",
                f"- 状态：{_status_label(record.status)}",
                f"- 总时长：{record.duration_seconds:.2f} 秒",
                f"- 运行目录：`{record.run_path}`" if record.run_path else "- 运行目录：未创建（离线知识或启动前失败）",
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
        if record.error:
            lines.extend(["", "### 受限或失败原因", "", record.error])
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
            f"- 不可变上下文：`{_short_ref(context.context_ref)}`"
            + (f"；语义版本：`{context.semantic_sha256[:12]}`" if context.semantic_sha256 else ""),
            "- 本题所有网络查询、潮流和 N-1（如有）均以这份只读上下文为边界；不会从回答文本猜测网络数据。",
        ]
    )


def _render_evidence(lines: list[str], observation: RunObservation) -> None:
    if observation.evidence_sources:
        for source in observation.evidence_sources:
            suffix = f"；关联结果 `{_short_ref(source.result_ref)}`" if source.result_ref else ""
            location = f"；文件 `{source.relative_path}`" if source.relative_path else ""
            lines.append(f"- {source.description}（由 `{source.capability}` 产生{suffix}{location}；引用 `{_short_ref(source.reference)}`）")
    elif observation.result_refs:
        lines.extend(f"- 已产生仿真结果：`{_short_ref(reference)}`（本题未提交单独证据引用）" for reference in observation.result_refs)
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
        return EvidenceSource(reference, "当前运行中记录的证据引用（内容不可读）", "unknown", None, str(path.relative_to(run_path)))
    capability = str(document.get("capability_id", "unknown"))
    result_ref = document.get("result_ref") if isinstance(document.get("result_ref"), str) else None
    return EvidenceSource(reference, _evidence_description(document), capability, result_ref, str(path.relative_to(run_path)))


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


def _short_ref(reference: str | None) -> str:
    if not reference:
        return ""
    prefix, _, digest = reference.rpartition(":")
    return f"{prefix}:{digest[:12]}…" if digest else reference


def _status_label(status: str) -> str:
    return {"success": "成功", "limited": "受限", "failed": "失败"}.get(status, status)
