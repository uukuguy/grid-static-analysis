from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from grid_agent.analysis.models import (
    AnalysisContext,
    AnalysisContextEvent,
    DiagnosticRecord,
    LimitationRecord,
    TurnRecord,
)
from grid_agent.analysis.workspace import AnalysisWorkspace


def render_analysis_report(
    *,
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    environment: Mapping[str, str],
) -> str:
    """Render a readable analysis narrative from finalized structured context."""
    diagnostics: list[str] = []
    ledger = _read_context_events(workspace.context_events_path)
    diagnostics.extend(ledger.diagnostics)
    trace = _read_trace_steps(workspace.trace_path, workspace.events_path)
    diagnostics.extend(trace.diagnostics)
    trace_pages = _write_turn_trace_pages(context, workspace, trace.steps, diagnostics)
    counts = {status: sum(turn.status == status for turn in context.turns) for status in ("success", "failed")}
    lines = [
        "# 系统仿真分析报告",
        "",
        f"- 分析编号：`{context.analysis_id}`",
        f"- 指令数：{context.input.instruction_count}；已完成：{len(context.turns)}；成功：{counts['success']}；未完成：{counts['failed']}",
        "",
        "## 本批次运行环境",
        "",
        *_render_environment(context, environment),
    ]
    for turn in sorted(context.turns, key=lambda item: item.ordinal):
        lines.extend(_render_narrative_turn(context, turn, workspace, trace.steps, trace_pages, diagnostics))
    audit = _render_audit_review(context, workspace, diagnostics)
    if audit:
        lines.extend(["", "## 完整性诊断", "", *audit])

    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class _TraceStep:
    sequence: int
    turn_id: str | None
    tool_call_id: str | None
    capability: str
    args: Mapping[str, Any]
    result: Mapping[str, Any]
    ok: bool
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class _TraceRead:
    steps: tuple[_TraceStep, ...]
    diagnostics: tuple[str, ...]


_READER_MAX_DEPTH = 6
_READER_MAX_MAPPING_ITEMS = 50
_READER_MAX_SEQUENCE_ITEMS = 20
_SECRET_FIELD_TOKENS = {
    "authorization",
    "credential",
    "credentials",
    "passwd",
    "password",
    "secret",
    "token",
}


def _render_narrative_turn(
    context: AnalysisContext,
    turn: TurnRecord,
    workspace: AnalysisWorkspace,
    trace_steps: Sequence[_TraceStep],
    trace_pages: Mapping[str, str],
    diagnostics: list[str],
) -> list[str]:
    limitations = [item for item in context.unresolved_limitations if item.turn_id == turn.turn_id]
    answer = _reader_answer(_accepted_answer_text(turn, workspace, limitations, diagnostics))
    steps = _steps_for_turn(context, turn.turn_id, trace_steps)
    trace_link = (
        _workspace_link(
            workspace,
            trace_pages[turn.turn_id],
            label="查看本题调用输入、输出和原始工件",
            unavailable_label="轨迹页不可用",
            diagnostics=diagnostics,
            description="详细执行轨迹",
        )
        + "。"
        if turn.turn_id in trace_pages
        else "详细执行轨迹不可用。"
    )
    lines = [
        "",
        f"## {turn.ordinal}. {_md(turn.instruction)}",
        "",
        "### 回答",
        "",
        answer if turn.answer_path else "模型未返回可接受的最终回答。",
        "",
        "### 仿真环境上下文",
        "",
        *_render_turn_context(context, turn, steps, workspace, diagnostics),
        "",
        "### 智能体分析轨迹",
        "",
        *_render_trace_steps(steps),
        "",
        "### 执行状态与证据",
        "",
        f"- 状态：{_reader_status(turn.status)}",
        f"- 总时长：{turn.duration_seconds:.2f} 秒" if turn.duration_seconds is not None else "- 总时长：未记录",
        f"- 原始回答：{_answer_link_or_label(turn, workspace, diagnostics)}",
        *_render_turn_evidence(context, turn, workspace, diagnostics),
        f"- 详细执行轨迹：{trace_link}",
    ]
    return lines


def _render_turn_context(
    context: AnalysisContext,
    turn: TurnRecord,
    steps: Sequence[_TraceStep],
    workspace: AnalysisWorkspace,
    diagnostics: list[str],
) -> list[str]:
    lines = [_active_model_line(context)]
    calculations = [
        item for item in context.domain_state.calculations.values() if item.producer_turn_id == turn.turn_id
    ]
    scenarios = [item for item in context.domain_state.scenarios.values() if item.producer_turn_id == turn.turn_id]
    constraints = [item for item in context.domain_state.constraints.values() if item.producer_turn_id == turn.turn_id]
    if calculations and not constraints:
        constraints = list(context.domain_state.constraints.values())
    lines.extend(_constraint_lines(constraints))
    lines.extend(_calculation_lines(calculations))
    lines.extend(_scenario_lines(scenarios))
    reused_calculations = [
        context.domain_state.calculations[reference]
        for reference in turn.consumed_refs
        if reference in context.domain_state.calculations
    ]
    if reused_calculations:
        labels = "、".join(_calculation_label(item.kind) for item in reused_calculations)
        lines.append(f"- 复用前序计算：{labels}。")
    if len(lines) == 1:
        lines.append("- 本题未新增或复用领域计算状态。")
    lines.extend([
        f"- 状态变化：复用前序工件 {len(turn.consumed_refs)} 项；新增工件 {len(turn.produced_refs)} 项。",
        "- 执行边界：模型上下文为只读冻结快照；下列过程记录的是本题实际调用的已发布工具。",
        f"- {_workspace_link(workspace, workspace.context_snapshot_path.relative_to(workspace.root_path), label='查看连续分析上下文', unavailable_label='上下文文件不可用', diagnostics=diagnostics, description='连续分析上下文')}。",
    ])
    return lines


def _active_model_line(context: AnalysisContext) -> str:
    model = context.domain_state.model
    if model is not None:
        label = "IEEE-39" if model.model_id == "ieee39" else model.model_id
        counts = "，".join(f"{key} {value}" for key, value in model.counts.items()) or "规模未记录"
        return f"- 活动模型：{label}（{model.source}）；{counts}。"
    return "- 活动模型：尚未登记。"


def _constraint_lines(constraints: Sequence[Any]) -> list[str]:
    lines: list[str] = []
    for item in constraints[:4]:
        source = "模型数据" if item.source_kind == "model" else item.source_kind
        if item.quantity == "bus.vm_pu" and item.lower is not None and item.upper is not None:
            lines.append(f"- 母线电压约束：{item.lower:g}–{item.upper:g} {item.unit}（{source}）。")
        elif item.upper is not None:
            lines.append(
                f"- {_constraint_label(item.quantity, item.subject_kind)}："
                f"≤{item.upper:g} {_display_unit(item.unit)}（{source}）。"
            )
        elif item.lower is not None:
            lines.append(
                f"- {_constraint_label(item.quantity, item.subject_kind)}："
                f"≥{item.lower:g} {_display_unit(item.unit)}（{source}）。"
            )
    return lines


def _constraint_label(quantity: str, subject_kind: str) -> str:
    if quantity == "branch.loading_percent":
        return {"line": "线路负载约束", "trafo": "变压器负载约束"}.get(subject_kind, "支路负载约束")
    return quantity


def _display_unit(unit: str) -> str:
    return "%" if unit == "percent" else unit


def _calculation_lines(calculations: Sequence[Any]) -> list[str]:
    status_labels = {"converged": "已收敛", "succeeded": "已完成", "partial": "部分完成", "failed": "失败"}
    return [
        f"- {_calculation_label(item.kind)}：{status_labels.get(item.status, item.status)}。"
        for item in calculations[:4]
    ]


def _calculation_label(kind: str) -> str:
    return {
        "powerflow.ac": "交流潮流",
        "contingency.n_minus_one": "N-1 静态校核",
    }.get(kind, kind)


def _scenario_lines(scenarios: Sequence[Any]) -> list[str]:
    status_labels = {"succeeded": "完成", "non_converged": "未收敛", "failed": "失败"}
    return [
        f"- 场景 {_scenario_label(item.kind)}：{status_labels.get(item.status, item.status)}。"
        for item in scenarios[:4]
    ]


def _scenario_label(kind: str) -> str:
    return {"single_branch_outage": "单支路停运"}.get(kind, kind)


def _render_trace_steps(steps: Sequence[_TraceStep]) -> list[str]:
    if not steps:
        return ["未观察到与本题关联的领域工具调用。"]
    lines: list[str] = []
    for ordinal, step in enumerate(steps, start=1):
        state = "完成" if step.ok else "返回受限/错误"
        duration = f"，{step.duration_seconds:.2f} 秒" if step.duration_seconds is not None else ""
        lines.append(f"{ordinal}. {_trace_step_summary(step)}（`{step.capability}`，{state}{duration}）")
    return lines


def _render_tool_results(steps: Sequence[_TraceStep]) -> list[str]:
    if not steps:
        return ["未观察到与本题关联的领域工具调用。"]
    lines: list[str] = []
    for ordinal, step in enumerate(steps, start=1):
        state = "完成" if step.ok else "返回受限/错误"
        duration = f"，{step.duration_seconds:.2f} 秒" if step.duration_seconds is not None else ""
        projected = _reader_result_value(step.result)
        lines.append(f"{ordinal}. {_trace_step_summary(step)}（`{step.capability}`，{state}{duration}）")
        lines.extend(
            [
                f"   - 能力：`{step.capability}`",
                f"   - 状态：{state}",
                f"   - 耗时：{step.duration_seconds:.2f} 秒" if step.duration_seconds is not None else "   - 耗时：未记录",
            ]
        )
        if isinstance(projected, Mapping) and not projected:
            lines.append("   - 结果为空。")
            continue
        lines.extend(
            [
                "   - 结果：",
                "",
                "```json",
                _reader_json(projected),
                "```",
            ]
        )
    return lines


def _reader_result_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _READER_MAX_DEPTH:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        projected_mapping: dict[str, Any] = {}
        visible = [
            (str(key), item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_internal_or_secret_field(str(key))
        ]
        for key, item in visible[:_READER_MAX_MAPPING_ITEMS]:
            projected_mapping[key] = _reader_result_value(item, depth=depth + 1)
        if len(visible) > _READER_MAX_MAPPING_ITEMS:
            projected_mapping["_omitted_fields"] = len(visible) - _READER_MAX_MAPPING_ITEMS
        return projected_mapping
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        projected_sequence = [
            _reader_result_value(item, depth=depth + 1)
            for item in value[:_READER_MAX_SEQUENCE_ITEMS]
        ]
        if len(value) > _READER_MAX_SEQUENCE_ITEMS:
            projected_sequence.append({"_omitted_items": len(value) - _READER_MAX_SEQUENCE_ITEMS})
        return projected_sequence
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _is_internal_or_secret_field(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("_ref") or lowered.endswith("_refs"):
        return True
    tokens = _field_name_tokens(key)
    if any(token in _SECRET_FIELD_TOKENS for token in tokens):
        return True
    pairs = set(zip(tokens, tokens[1:], strict=False))
    if ("api", "key") in pairs or ("private", "key") in pairs:
        return True
    compact = "".join(tokens)
    return compact.endswith("apikey") or compact.endswith("privatekey")


def _field_name_tokens(key: str) -> tuple[str, ...]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return tuple(token for token in re.split(r"[^A-Za-z0-9]+", separated.lower()) if token)


def _reader_json(value: Any) -> str:
    return _redact_internal_refs(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _trace_step_summary(step: _TraceStep) -> str:
    if step.capability == "context.open":
        model = step.result.get("model")
        return f"打开只读网络仿真环境上下文：{model}" if isinstance(model, str) else "打开只读网络仿真环境上下文"
    if step.capability == "analysis.powerflow.ac.run" and step.result.get("converged") is True:
        loss = step.result.get("total_active_loss")
        if isinstance(loss, Mapping) and isinstance(loss.get("value"), (int, float)):
            return f"运行交流潮流计算：收敛，有功网损 {loss['value']:.4f} {loss.get('unit', 'MW')}"
        return "运行交流潮流计算：潮流收敛"
    if step.capability == "analysis.contingency.n_minus_one.run":
        count = step.result.get("scenario_count")
        return f"执行单支路 N-1 静态安全校核：完成 {count} 个场景" if isinstance(count, int) else "执行单支路 N-1 静态安全校核"
    return {
        "environment.describe": "核对仿真器协议和已发布能力",
        "model.list": "确认可用的已注册网络模型",
        "context.get": "读取已打开的仿真环境上下文",
        "model.element.get": "定位问题涉及的网络元件",
        "model.dataset.describe": "核对可查询的数据集与字段",
        "model.dataset.query": "查询网络模型数据",
        "model.constraints.describe": "读取活动模型内定义的约束",
        "topology.branch.endpoints.get": "核查支路两端母线",
        "topology.components.get": "核查网络拓扑连通性",
        "result.branches.rank": "按支路运行指标筛选和排序",
        "evidence.get": "读取已持久化的仿真证据",
        "grid_guide_open": "读取已发布的领域操作指南",
        "grid_submit_answer": "提交本题回答",
    }.get(step.capability, "调用已发布的领域能力")


def _render_turn_evidence(
    context: AnalysisContext,
    turn: TurnRecord,
    workspace: AnalysisWorkspace,
    diagnostics: list[str],
) -> list[str]:
    produced = set(turn.produced_refs)
    references = dict.fromkeys([*turn.produced_refs, *turn.consumed_refs])
    records = [(context.evidence[reference], "本题生成" if reference in produced else "复用前序分析") for reference in references if reference in context.evidence]
    if not records:
        return ["本题没有可追溯的仿真证据。"]
    lines: list[str] = []
    for record, origin in records[:4]:
        title = _evidence_title(record.capability, record.summary)
        location = _workspace_link(workspace, record.path, label="查看证据工件", unavailable_label="证据工件不可用", diagnostics=diagnostics, description="仿真证据")
        lines.append(f"- {title}（{origin}；{location}）。")
    if len(records) > 4:
        lines.append(f"- 其余 {len(records) - 4} 个场景证据已保存在本次分析目录，避免用重复条目掩盖主要结论。")
    return lines


def _evidence_title(capability: str | None, summary: Mapping[str, Any]) -> str:
    capability = capability or _first_string(summary, ("capability_id",))
    labels = {
        "topology.branch.endpoints.get": "网络拓扑事实",
        "model.constraints.describe": "模型约束数据",
        "analysis.powerflow.ac.run": "交流潮流计算证据",
        "analysis.contingency.n_minus_one.run": "N-1 场景证据",
    }
    fallback = _first_string(summary, ("title", "description")) or "当前运行持久化的仿真证据"
    return labels.get(capability, fallback) if capability else fallback


def _write_turn_trace_pages(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    trace_steps: Sequence[_TraceStep],
    diagnostics: list[str],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for turn in context.turns:
        path = workspace.turn_path(turn.ordinal) / "trace.md"
        limitations = tuple(
            item
            for item in context.unresolved_limitations
            if item.turn_id == turn.turn_id
        )
        try:
            _write_text_atomic(
                path,
                _render_turn_trace_page(
                    turn,
                    _steps_for_turn(context, turn.turn_id, trace_steps),
                    limitations,
                    workspace,
                    path,
                    diagnostics,
                ),
            )
        except OSError:
            diagnostics.append(f"回合 {turn.ordinal} 详细执行轨迹不可写入")
            continue
        paths[turn.turn_id] = str(path.relative_to(workspace.root_path))
    return paths


def _render_turn_trace_page(
    turn: TurnRecord,
    steps: Sequence[_TraceStep],
    limitations: Sequence[LimitationRecord],
    workspace: AnalysisWorkspace,
    path: Path,
    diagnostics: list[str],
) -> str:
    lines = ["# 详细执行轨迹", "", f"## {turn.ordinal}. {_md(turn.instruction)}", ""]
    if limitations:
        lines.extend(
            [
                "### 失败诊断",
                "",
                *(
                    f"- {_reader_diagnostic(limitation.message)}"
                    for limitation in limitations
                ),
                "",
            ]
        )
    if not steps:
        lines.append("未观察到与本题关联的领域工具调用。")
        return "\n".join(lines) + "\n"
    for ordinal, step in enumerate(steps, start=1):
        state = "完成" if step.ok else "返回受限/错误"
        lines.extend(
            [
                f"### {ordinal}. {_trace_step_summary(step)}",
                "",
                f"- 能力：`{step.capability}`",
                f"- 状态：{state}",
                f"- 耗时：{step.duration_seconds:.2f} 秒" if step.duration_seconds is not None else "- 耗时：未记录",
                "",
                "### 输入",
                "",
                "```json",
                _trace_json(step.args),
                "```",
                "",
                "### 输出摘要",
                "",
                "```json",
                _trace_json(step.result),
                "```",
                "",
                "### 原始工件",
                "",
                f"- {_turn_trace_tool_result_link(workspace, path, turn.turn_id, step.tool_call_id, diagnostics)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _trace_json(value: Mapping[str, Any]) -> str:
    return _redact_internal_refs(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _turn_trace_tool_result_link(
    workspace: AnalysisWorkspace,
    trace_path: Path,
    turn_id: str,
    tool_call_id: str | None,
    diagnostics: list[str],
) -> str:
    if tool_call_id is None:
        return "原始工具结果工件不可用"
    candidates = [
        Path("tool-results")
        / turn_id
        / "compatibility"
        / f"{tool_call_id}.json"
    ]
    if not workspace.events_path.is_file():
        candidates.append(
            Path("tool-results") / turn_id / f"{tool_call_id}.json"
        )
    for relative in candidates:
        resolved = _normalize_workspace_relative_path(
            workspace,
            relative,
            diagnostics=diagnostics,
            description="原始工具结果工件",
        )
        if resolved is None or not resolved.absolute.is_file():
            continue
        href = Path(
            os.path.relpath(resolved.absolute, start=trace_path.parent)
        ).as_posix()
        return _link(href, "查看原始工具结果")
    return "原始工具结果工件不可用"


def _render_audit_review(context: AnalysisContext, workspace: AnalysisWorkspace, diagnostics: list[str]) -> list[str]:
    lines: list[str] = []
    if context.unresolved_limitations:
        lines.append("以下提示不改写已经提交的回答，只标记需要复核的执行事实。")
        for limitation in _unique_limitations(context.unresolved_limitations):
            lines.append(f"- {_reader_diagnostic(limitation.message)}")
    if diagnostics:
        lines.extend(f"- {_md(item)}" for item in dict.fromkeys(diagnostics))
    lines.extend(
        [
            f"- 完整上下文与调用轨迹：{_workspace_link(workspace, workspace.context_snapshot_path.relative_to(workspace.root_path), label='上下文', unavailable_label='路径不可用', diagnostics=diagnostics, description='上下文工件')}、{_workspace_link(workspace, workspace.trace_path.relative_to(workspace.root_path), label='调用轨迹', unavailable_label='路径不可用', diagnostics=diagnostics, description='调用轨迹工件')}。",
        ]
    )
    return lines


def _steps_for_turn(context: AnalysisContext, turn_id: str, trace_steps: Sequence[_TraceStep]) -> tuple[_TraceStep, ...]:
    call_ids: set[str] = set()
    sequences: set[int] = set()
    for observation in context.observations.values():
        if observation.turn_id != turn_id or not isinstance(observation.producer_observation, Mapping):
            continue
        producer = observation.producer_observation
        if isinstance(producer.get("tool_call_id"), str):
            call_ids.add(str(producer["tool_call_id"]))
        if isinstance(producer.get("trace_sequence"), int):
            sequences.add(int(producer["trace_sequence"]))
    return tuple(
        step
        for step in trace_steps
        if step.turn_id == turn_id
        or step.tool_call_id in call_ids
        or step.sequence in sequences
    )


def _read_trace_steps(path: Path, native_events_path: Path) -> _TraceRead:
    if not path.is_file():
        return _TraceRead((), ("调用轨迹不可用：trace/events.jsonl 缺失",))
    turns_by_call = _native_turns_by_call(native_events_path)
    starts: dict[str, tuple[int, datetime]] = {}
    steps: list[_TraceStep] = []
    diagnostics: list[str] = []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return _TraceRead((), ("调用轨迹不可用：trace/events.jsonl 不可读",))
    for line_number, line in enumerate(raw_lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"调用轨迹第 {line_number} 行格式错误")
            continue
        if not isinstance(event, Mapping) or event.get("event") != "pi_event" or not isinstance(event.get("payload"), Mapping):
            continue
        payload = event["payload"]
        call_id = payload.get("tool_call_id")
        timestamp = _trace_timestamp(event.get("timestamp"))
        if payload.get("type") == "tool_execution_start" and isinstance(call_id, str) and timestamp is not None:
            starts[call_id] = (int(event.get("sequence", 0)), timestamp)
        elif payload.get("type") == "tool_result" and isinstance(payload.get("capability"), str):
            duration = None
            if isinstance(call_id, str) and call_id in starts and timestamp is not None:
                duration = max(0.0, (timestamp - starts[call_id][1]).total_seconds())
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            args: Mapping[str, Any] = {}
            if isinstance(call_id, str) and call_id in starts:
                # Arguments are recovered from the matching start record below when available.
                pass
            normalized_call_id = call_id if isinstance(call_id, str) else None
            steps.append(
                _TraceStep(
                    int(event.get("sequence", 0)),
                    turns_by_call.get(normalized_call_id) if normalized_call_id is not None else None,
                    normalized_call_id,
                    str(payload["capability"]),
                    args,
                    result,
                    payload.get("ok") is True,
                    duration,
                )
            )
    # Populate arguments in a second pass without trusting result payloads.
    args_by_call = _trace_args_by_call(raw_lines)
    return _TraceRead(
        tuple(
            step.__class__(
                step.sequence,
                step.turn_id,
                step.tool_call_id,
                step.capability,
                args_by_call.get(step.tool_call_id, {}) if step.tool_call_id is not None else {},
                step.result,
                step.ok,
                step.duration_seconds,
            )
            for step in steps
        ),
        tuple(diagnostics),
    )


def _native_turns_by_call(path: Path) -> dict[str, str]:
    """Recover authoritative turn ownership from the native event scope.

    Compatibility observations are intentionally selective, so they cannot be
    used as the membership index for a complete execution narrative.
    """
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    turns: dict[str, str] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        scope = event.get("scope") if isinstance(event, Mapping) else None
        if not isinstance(scope, Mapping):
            continue
        call_id = scope.get("tool_call_id")
        turn_id = scope.get("turn_id")
        if isinstance(call_id, str) and isinstance(turn_id, str):
            turns[call_id] = turn_id
    return turns


def _trace_args_by_call(lines: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    values: dict[str, Mapping[str, Any]] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") if isinstance(event, Mapping) else None
        if not isinstance(payload, Mapping) or payload.get("type") != "tool_execution_start":
            continue
        if isinstance(payload.get("tool_call_id"), str) and isinstance(payload.get("args"), Mapping):
            values[str(payload["tool_call_id"])] = payload["args"]
    return values


def _trace_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def write_analysis_report_checkpoint(
    *,
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    environment: Mapping[str, str],
) -> None:
    report = render_analysis_report(context=context, workspace=workspace, environment=environment)
    _write_text_atomic(workspace.report_path, report)


def _append_section(lines: list[str], title: str, body: Sequence[str]) -> None:
    lines.extend([f"## {title}", "", *body, ""])


def _render_summary(context: AnalysisContext) -> list[str]:
    counts = {status: sum(turn.status == status for turn in context.turns) for status in ("success", "failed")}
    return [
        f"- analysis_id：`{context.analysis_id}`",
        f"- 最终状态：`{context.status}`；最终上下文修订：`{context.revision}`",
        f"- 指令数：{context.input.instruction_count}；完成回合：{len(context.turns)}；成功：{counts['success']}；失败：{counts['failed']}",
    ]


def _render_reader_summary(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    diagnostics: list[str],
) -> list[str]:
    counts = {status: sum(turn.status == status for turn in context.turns) for status in ("success", "failed")}
    lines = [
        f"- 共 {len(context.turns)}/{context.input.instruction_count} 题；成功 {counts['success']} 题；未完成 {counts['failed']} 题。",
        "",
        "| 题目 | 状态 | 结论摘要 |",
        "| --- | --- | --- |",
    ]
    for turn in sorted(context.turns, key=lambda item: item.ordinal):
        answer = _accepted_answer_text(turn, workspace, (), diagnostics)
        lines.append(f"| {turn.ordinal}. {_md(turn.instruction)} | {_reader_status(turn.status)} | {_md(_answer_preview(answer))} |")
    return lines


def _render_environment(context: AnalysisContext, environment: Mapping[str, str]) -> list[str]:
    lines = [
        f"- provider：`{context.runtime.provider}`",
        f"- model：`{context.runtime.model}`",
        f"- grid-capability protocol：`{context.runtime.grid_capability_protocol}`",
        f"- pandapower：`{context.runtime.pandapower_version}`",
    ]
    for key, value in environment.items():
        if key in {"provider", "model", "pandapower"}:
            continue
        lines.append(f"- {key}：`{_safe_scalar(value)}`")
    return lines


@dataclass(frozen=True, slots=True)
class _ResolvedWorkspacePath:
    absolute: Path
    relative: str


@dataclass(frozen=True, slots=True)
class _LedgerRead:
    events: tuple[AnalysisContextEvent, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _TurnRevisionRanges:
    ranges: dict[str, tuple[int, int]]
    diagnostics: tuple[str, ...]


def _render_baselines(context: AnalysisContext, workspace: AnalysisWorkspace, diagnostics: list[str]) -> list[str]:
    if not context.baselines:
        return ["未注册仿真基线。"]
    rows = ["| 模型 | 来源 | 仿真器 | 工件 |", "| --- | --- | --- | --- |"]
    omitted = 0
    seen_sources: set[tuple[str, str]] = set()
    for baseline in context.baselines.values():
        model = _first_string(baseline.source, ("model", "name", "network")) or "unknown"
        source = _first_string(baseline.source, ("source", "dataset", "module")) or "unknown"
        key = (model, source)
        if key in seen_sources:
            omitted += 1
            continue
        seen_sources.add(key)
        engine = _first_string(baseline.network, ("engine", "solver")) or "pandapower"
        version = _first_string(baseline.network, ("pandapower_version", "engine_version", "version"))
        engine_display = f"{engine} {version}" if version else engine
        rows.append(
            "| "
            + " | ".join(
                (
                    _md(model),
                    _md(source),
                    _md(engine_display),
                    _workspace_link(
                        workspace,
                        baseline.path,
                        label=baseline.path,
                        unavailable_label="路径不可用",
                        diagnostics=diagnostics,
                        description="仿真基线工件",
                    ),
                )
            )
            + " |"
        )
    if omitted:
        rows.append(f"补充基线 {omitted} 项与上表来源相同，未重复展开。")
    return rows


def _render_final_context(context: AnalysisContext, workspace: AnalysisWorkspace, diagnostics: list[str]) -> list[str]:
    return [
        f"- 上下文文件：{_workspace_link(workspace, workspace.context_snapshot_path.relative_to(workspace.root_path), label='context/analysis-context.json', unavailable_label='上下文文件不可用', diagnostics=diagnostics, description='上下文文件')}",
        f"- 事件账本：{_workspace_link(workspace, workspace.context_events_path.relative_to(workspace.root_path), label='context/context-events.jsonl', unavailable_label='事件账本不可用', diagnostics=diagnostics, description='事件账本')}",
        f"- 当前活动回合：{context.current_turn.turn_id if context.current_turn else '无'}",
        f"- 已注册结果：{len(context.results)}；证据：{len(context.evidence)}；已验证事实：{len(context.verified_facts)}；诊断：{len(context.diagnostics)}",
    ]


def _render_dependencies(context: AnalysisContext, workspace: AnalysisWorkspace, diagnostics: list[str]) -> list[str]:
    rows = ["| 引用 | 类型 | 生产回合 | 依赖 | 工件 |", "| --- | --- | --- | --- | --- |"]
    for result in context.results.values():
        rows.append(
            _dependency_row(
                ref=result.result_ref,
                kind="result",
                turn_id=result.turn_id,
                deps=[result.revision_ref, *result.evidence_refs],
                path=result.path,
                workspace=workspace,
                diagnostics=diagnostics,
            )
        )
    for evidence in context.evidence.values():
        rows.append(
            _dependency_row(
                ref=evidence.evidence_ref,
                kind=evidence.kind,
                turn_id=evidence.turn_id,
                deps=evidence.refs,
                path=evidence.path,
                workspace=workspace,
                diagnostics=diagnostics,
            )
        )
    for observation in context.observations.values():
        rows.append(
            _dependency_row(
                ref=observation.observation_ref,
                kind="observation",
                turn_id=observation.turn_id,
                deps=observation.consumed_refs,
                path=observation.path,
                workspace=workspace,
                diagnostics=diagnostics,
            )
        )
    return rows if len(rows) > 2 else ["没有注册结果、证据或工具观察。"]


def _dependency_row(
    *,
    ref: str,
    kind: str,
    turn_id: str | None,
    deps: Sequence[str],
    path: str,
    workspace: AnalysisWorkspace,
    diagnostics: list[str],
) -> str:
    return (
        "| "
        + " | ".join(
            (
                f"`{_md(ref)}`",
                _md(kind),
                _md(turn_id or "全局"),
                "<br>".join(f"`{_md(dep)}`" for dep in deps) if deps else "—",
                _workspace_link(
                    workspace,
                    path,
                    label=path,
                    unavailable_label="路径不可用",
                    diagnostics=diagnostics,
                    description=f"{kind} 工件",
                ),
            )
        )
        + " |"
    )


def _render_timeline(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    turn_revisions: Mapping[str, tuple[int, int]],
    diagnostics: list[str],
) -> list[str]:
    if not context.turns:
        return ["尚无完成回合。"]

    diagnostics_by_turn: dict[str, list[DiagnosticRecord]] = defaultdict(list)
    for diagnostic in context.diagnostics:
        if diagnostic.turn_id:
            diagnostics_by_turn[diagnostic.turn_id].append(diagnostic)

    limitations_by_turn: dict[str, list[LimitationRecord]] = defaultdict(list)
    for limitation in context.unresolved_limitations:
        if limitation.turn_id:
            limitations_by_turn[limitation.turn_id].append(limitation)

    lines: list[str] = []
    for turn in sorted(context.turns, key=lambda item: item.ordinal):
        revision_range = turn_revisions.get(turn.turn_id)
        revision_display = f"{revision_range[0]} → {revision_range[1]}" if revision_range else "不可用"
        lines.extend(
            [
                f"### {turn.ordinal}. {turn.instruction}",
                "",
                f"- turn_id：`{turn.turn_id}`；状态：{turn.status}；上下文版本：{revision_display}",
                f"- 耗时：{turn.duration_seconds:.2f} 秒" if turn.duration_seconds is not None else "- 耗时：未记录",
                f"- 接受答案：{_answer_link_or_label(turn, workspace, diagnostics)}",
                "- answer_output：",
                "",
                _accepted_answer_text(turn, workspace, limitations_by_turn.get(turn.turn_id, ()), diagnostics),
                "",
                f"- 复用前序结果：{_refs(turn.consumed_refs)}",
                f"- 新增工件：{_refs(turn.produced_refs)}",
            ]
        )
        turn_diagnostics = diagnostics_by_turn.get(turn.turn_id, [])
        if turn_diagnostics:
            lines.extend(["- 审计诊断："])
            for diagnostic in turn_diagnostics:
                lines.append(
                    f"  - `{_md(diagnostic.details.get('severity', 'diagnostic'))}` {_md(diagnostic.message)}"
                    + (f"（引用 `{_md(str(diagnostic.details.get('reference')))}`）" if diagnostic.details.get("reference") else "")
                )
        if limitations_by_turn.get(turn.turn_id):
            lines.extend(["- 回合限制："])
            for limitation in limitations_by_turn[turn.turn_id]:
                lines.append(f"  - {_md(limitation.message)}；相关引用：{_refs(limitation.refs)}")
        lines.append("")
    return lines


def _render_reader_turns(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    events: Sequence[AnalysisContextEvent],
    diagnostics: list[str],
) -> list[str]:
    if not context.turns:
        return ["尚无完成题目。"]
    limitations_by_turn: dict[str, list[LimitationRecord]] = defaultdict(list)
    for limitation in context.unresolved_limitations:
        if limitation.turn_id:
            limitations_by_turn[limitation.turn_id].append(limitation)
    observations_by_turn: dict[str, list[tuple[int, Any]]] = defaultdict(list)
    event_order = {
        str(event.payload.get("observation_ref")): event.sequence
        for event in events
        if event.event_type == "tool.observation.recorded"
    }
    for observation in context.observations.values():
        observations_by_turn[observation.turn_id].append((event_order.get(observation.observation_ref, 1_000_000), observation))

    lines: list[str] = []
    for turn in sorted(context.turns, key=lambda item: item.ordinal):
        answer = _accepted_answer_text(turn, workspace, limitations_by_turn.get(turn.turn_id, ()), diagnostics)
        lines.extend(
            [
                f"### {turn.ordinal}. {_md(turn.instruction)}",
                "",
                f"状态：{_reader_status(turn.status)}" + (f"；耗时 {turn.duration_seconds:.1f} 秒" if turn.duration_seconds is not None else ""),
                f"原始回答：{_answer_link_or_label(turn, workspace, diagnostics)}",
                "",
                "#### 回答",
                "",
                _reader_answer(answer),
                "",
                "#### 工具执行过程",
                "",
                *_render_tool_steps(observations_by_turn.get(turn.turn_id, ())),
            ]
        )
        turn_limitations = limitations_by_turn.get(turn.turn_id, ())
        if turn_limitations:
            lines.extend(["", "#### 审计诊断", ""])
            lines.extend(f"- {_reader_diagnostic(item.message)}" for item in _unique_limitations(turn_limitations))
        lines.append("")
    return lines


def _render_tool_steps(observations: Sequence[tuple[int, Any]]) -> list[str]:
    if not observations:
        return ["- 本回合没有记录到工具调用。"]
    lines: list[str] = []
    for ordinal, (_, observation) in enumerate(sorted(observations, key=lambda item: (item[0], item[1].observation_ref)), start=1):
        producer = observation.producer_observation
        args = producer.get("args") if isinstance(producer, Mapping) else {}
        args = args if isinstance(args, Mapping) else {}
        label = _tool_label(observation.capability)
        input_summary = _tool_input_summary(args)
        outcome = _tool_outcome_summary(observation.summary)
        detail = "；".join(item for item in (input_summary, outcome) if item)
        lines.append(f"{ordinal}. **{label}**" + (f"：{_md(detail)}。" if detail else "。"))
    return lines


def _render_audit_appendix(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    environment: Mapping[str, str],
    diagnostics: list[str],
) -> list[str]:
    lines = [
        "以下内容用于复核，不影响正文中的问题、回答和工具过程阅读。",
        "",
        "### 运行环境",
        "",
        *_render_environment(context, environment),
        "",
        "### 仿真基线",
        "",
        *_render_baselines(context, workspace, diagnostics),
    ]
    limitation_body = _render_limitations(context)
    if limitation_body:
        lines.extend(["", "### 审计诊断", "", *_render_compact_limitations(context)])
    if diagnostics:
        lines.extend(["", "### 报告生成诊断", "", *[f"- {_md(item)}" for item in dict.fromkeys(diagnostics)]])
    lines.extend(
        [
            "",
            "### 复核工件",
            "",
            *_render_forensic_artifacts(workspace, diagnostics),
            "",
            "<details>",
            "<summary>展开完整引用与工件索引（仅用于复核）</summary>",
            "",
            *_render_dependencies(context, workspace, diagnostics),
            "",
            "</details>",
        ]
    )
    return lines


def _reader_status(status: str) -> str:
    return "已完成" if status == "success" else "未完成"


def _answer_preview(answer: str) -> str:
    return _reader_answer(answer).replace("\n", " ")[:160].rstrip() + ("…" if len(_reader_answer(answer).replace("\n", " ")) > 160 else "")


def _reader_answer(answer: str) -> str:
    answer = _redact_internal_refs(answer)
    return answer if answer.strip() else "未提供回答。"


def _reader_diagnostic(message: str) -> str:
    labeled = re.sub(
        r"\b(context|revision|result|evidence|observation|constraint):"
        r"sha256:[0-9a-f]{4,64}(?:\.\.\.)?",
        lambda match: f"[{match.group(1)} 类型引用]",
        message,
    )
    labeled = re.sub(
        r"\basset:([^\s:]+):sha256:[0-9a-f]{4,64}",
        lambda match: f"[asset/{match.group(1)} 类型引用]",
        labeled,
    )
    return _redact_internal_refs(labeled)


def _redact_internal_refs(value: str) -> str:
    reference = (
        r"(?:context|revision|result|evidence|observation|constraint):"
        r"sha256:[0-9a-f]{4,64}(?:\.\.\.)?"
        r"|asset:[^\s:]+:sha256:[0-9a-f]{4,64}"
    )
    cleaned = re.sub(rf"[（(]\s*(?:{reference})\s*[）)]", "", value)
    cleaned = re.sub(rf"[，,]\s*上下文\s+(?:{reference})", "", cleaned)
    cleaned = re.sub(rf"(?:[，,]\s*)?证据引用\s+(?:{reference})", "", cleaned)
    cleaned = re.sub(reference, "", cleaned)
    cleaned = re.sub(r"[（(]\s*(?:[，,；;、]|与|和|\s)*[）)]", "", cleaned)
    cleaned = re.sub(r"([，,；;])\s*(?:与|和|、)\s*(?=[，,；;。．）)])", r"\1", cleaned)
    cleaned = re.sub(r"\s+([，。；：,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([。．])(?:\s*[。．])+", r"\1", cleaned)
    return cleaned


def _tool_label(capability: str) -> str:
    return {
        "model.list": "读取模型目录",
        "environment.describe": "读取仿真环境",
        "context.open": "打开电网模型",
        "model.element.get": "查询网络元件",
        "model.dataset.query": "查询网络数据",
        "topology.branch.endpoints.get": "查询线路端点",
        "evidence.get": "读取仿真证据",
        "analysis.powerflow.ac.run": "执行交流潮流",
        "result.branches.rank": "按负载率排序",
        "analysis.contingency.n_minus_one.run": "执行 N-1 校核",
        "grid_submit_answer": "提交本题回答",
        "guide.open": "读取操作指南",
    }.get(capability, capability)


def _tool_input_summary(args: Mapping[str, Any]) -> str:
    if isinstance(args.get("model_id"), str):
        return f"模型 {args['model_id']}"
    if isinstance(args.get("identifier"), str):
        kind = "线路" if args.get("kind") == "line" else str(args.get("kind", "元件"))
        return f"{kind} {args['identifier']}"
    if isinstance(args.get("dataset"), str):
        return {"network.buses": "查询母线数据", "network.branches": "查询支路数据"}.get(args["dataset"], f"查询 {args['dataset']}")
    if isinstance(args.get("branch_refs"), list):
        return f"校核 {len(args['branch_refs'])} 条线路"
    if isinstance(args.get("result_ref"), str):
        return "复用已注册仿真结果"
    if isinstance(args.get("metric"), str):
        limit = args.get("limit")
        return f"指标 {args['metric']}" + (f"，前 {limit} 项" if isinstance(limit, int) else "")
    if isinstance(args.get("context_ref"), str):
        return "基于已打开模型"
    return ""


def _tool_outcome_summary(summary: Mapping[str, Any]) -> str:
    if summary.get("ok") is False:
        return "调用未成功"
    details: list[str] = []
    if summary.get("converged") is True:
        details.append("潮流收敛")
    if isinstance(summary.get("total_active_loss"), (int, float)):
        details.append(f"有功网损 {summary['total_active_loss']:.3f} MW")
    if isinstance(summary.get("scenario_count"), int):
        details.append(f"完成 {summary['scenario_count']} 个场景")
    if isinstance(summary.get("status"), str):
        details.append(f"状态 {summary['status']}")
    if summary.get("result_ref"):
        details.append("已生成可追溯结果")
    if summary.get("evidence_ref"):
        details.append("已生成可追溯证据")
    return "；".join(details) if details else "调用完成"


def _unique_limitations(limitations: Sequence[LimitationRecord]) -> list[LimitationRecord]:
    unique: dict[str, LimitationRecord] = {}
    for item in limitations:
        unique.setdefault(item.message, item)
    return list(unique.values())


def _render_compact_limitations(context: AnalysisContext) -> list[str]:
    grouped: dict[str, list[LimitationRecord]] = defaultdict(list)
    for limitation in context.unresolved_limitations:
        grouped[limitation.message].append(limitation)
    return [f"- {_reader_diagnostic(message)}（出现 {len(items)} 次）" for message, items in grouped.items()]


def _render_limitations(context: AnalysisContext) -> list[str]:
    if not context.unresolved_limitations:
        return []
    lines = ["| 限制 | 回合 | 相关引用 |", "| --- | --- | --- |"]
    for limitation in context.unresolved_limitations:
        lines.append(
            "| "
            + " | ".join(
                (
                    _md(limitation.message),
                    _md(limitation.turn_id or "全局"),
                    _refs(limitation.refs),
                )
            )
            + " |"
        )
    return lines


def _render_forensic_artifacts(workspace: AnalysisWorkspace, diagnostics: list[str]) -> list[str]:
    artifact_paths = (
        workspace.manifest_path,
        workspace.copied_instructions_path,
        workspace.answers_path,
        workspace.context_snapshot_path,
        workspace.context_events_path,
        workspace.trace_path,
    )
    lines = []
    for path in artifact_paths:
        relative = path.relative_to(workspace.root_path)
        lines.append(
            f"- {_workspace_link(workspace, relative, label=str(relative), unavailable_label='路径不可用', diagnostics=diagnostics, description='复核工件')}"
        )
    return lines


def _accepted_answer_text(
    turn: TurnRecord,
    workspace: AnalysisWorkspace,
    limitations: Sequence[LimitationRecord],
    diagnostics: list[str],
) -> str:
    if turn.answer_path:
        document = _read_workspace_json(
            workspace,
            turn.answer_path,
            diagnostics=diagnostics,
            description=f"回合 {turn.turn_id} 接受答案",
        )
        if isinstance(document, Mapping) and isinstance(document.get("answer_output"), str):
            return str(document["answer_output"])
        return "接受答案文件不可读；请复核注册路径。"
    if limitations:
        return "本题未生成回答：" + _reader_diagnostic(limitations[0].message)
    return "本回合未注册接受答案。"


def _answer_link_or_label(turn: TurnRecord, workspace: AnalysisWorkspace, diagnostics: list[str]) -> str:
    if not turn.answer_path:
        return "无接受答案文件"
    return _workspace_link(
        workspace,
        turn.answer_path,
        label=turn.answer_path,
        unavailable_label="路径不可用",
        diagnostics=diagnostics,
        description=f"回合 {turn.turn_id} 接受答案",
    )


def _read_context_events(path: Path) -> _LedgerRead:
    if not path.is_file():
        return _LedgerRead((), ("事件账本不可用：context/context-events.jsonl 缺失",))
    events: list[AnalysisContextEvent] = []
    diagnostics: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return _LedgerRead((), ("事件账本不可用：context/context-events.jsonl 不可读",))
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            events.append(AnalysisContextEvent.model_validate_json(line))
        except (ValueError, ValidationError):
            diagnostics.append(f"事件账本第 {line_number} 行格式错误；该报告不推断回合修订范围")
    return _LedgerRead(tuple(events), tuple(diagnostics))


def _turn_revision_ranges(events: Sequence[AnalysisContextEvent], turns: Sequence[TurnRecord]) -> _TurnRevisionRanges:
    ranges: dict[str, list[int]] = {}
    diagnostics: list[str] = []
    for event in events:
        if not event.turn_id:
            continue
        if event.event_type == "turn.started":
            ranges[event.turn_id] = [event.next_revision, event.next_revision]
        elif event.turn_id in ranges:
            ranges[event.turn_id][1] = max(ranges[event.turn_id][1], event.next_revision)
    completed_turn_ids = {turn.turn_id for turn in turns}
    for turn_id in sorted(completed_turn_ids - set(ranges)):
        diagnostics.append(f"事件账本缺少回合 {turn_id} 的修订数据；上下文版本标记为不可用")
    return _TurnRevisionRanges({turn_id: (values[0], values[1]) for turn_id, values in ranges.items()}, tuple(diagnostics))


def _read_workspace_json(
    workspace: AnalysisWorkspace,
    value: str | Path,
    *,
    diagnostics: list[str],
    description: str,
) -> object:
    resolved = _normalize_workspace_relative_path(workspace, value, diagnostics=diagnostics, description=description)
    if resolved is None:
        return None
    try:
        return json.loads(resolved.absolute.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        diagnostics.append(f"{description} 不可读")
        return None


def _normalize_workspace_relative_path(
    workspace: AnalysisWorkspace,
    value: str | Path,
    *,
    diagnostics: list[str],
    description: str,
) -> _ResolvedWorkspacePath | None:
    raw = str(value)
    path = Path(raw)
    if path.is_absolute():
        diagnostics.append(f"{description} 路径不可用：拒绝绝对路径")
        return None
    if ".." in path.parts:
        diagnostics.append(f"{description} 路径不可用：拒绝路径穿越")
        return None
    try:
        root = workspace.root_path.resolve(strict=False)
        resolved = (root / path).resolve(strict=False)
        relative = resolved.relative_to(root)
    except ValueError:
        diagnostics.append(f"{description} 路径不可用：解析结果不在工作区内")
        return None
    if str(relative) in {"", "."}:
        diagnostics.append(f"{description} 路径不可用：路径为空")
        return None
    return _ResolvedWorkspacePath(absolute=resolved, relative=relative.as_posix())


def _workspace_link(
    workspace: AnalysisWorkspace,
    value: str | Path,
    *,
    label: str,
    unavailable_label: str,
    diagnostics: list[str],
    description: str,
) -> str:
    resolved = _normalize_workspace_relative_path(workspace, value, diagnostics=diagnostics, description=description)
    if resolved is None:
        return unavailable_label
    return _link(resolved.relative, label)


def _link(path: Path | str, label: str) -> str:
    path_object = Path(path)
    href = path_object.as_posix()
    return f"[{_md(label)}]({href})"


def _refs(refs: Sequence[str]) -> str:
    return "，".join(f"`{_md(ref)}`" for ref in refs) if refs else "无"


def _first_string(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _safe_scalar(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return path.name
    return value


def _md(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
