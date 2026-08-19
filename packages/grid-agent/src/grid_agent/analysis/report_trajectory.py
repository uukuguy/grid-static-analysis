from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceStep:
    sequence: int
    turn_id: str | None
    tool_call_id: str | None
    capability: str
    args: Mapping[str, Any]
    result: Mapping[str, Any]
    ok: bool
    duration_seconds: float | None


@dataclass(frozen=True, slots=True)
class TraceDecision:
    turn_id: str | None
    tool_call_id: str | None
    intent: str
    decision: str
    next_action: str
    support_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrajectoryMilestone:
    title: str
    capabilities: tuple[str, ...]
    status: str
    duration_seconds: float | None
    detail: str
    decision: str | None = None
    important: bool = False
    step_turn_ids: tuple[str, ...] = ()
    step_tool_call_ids: tuple[str, ...] = ()
    step_sequences: tuple[int, ...] = ()
    support_refs: tuple[str, ...] = ()
    semantic_signature: str | None = None


_KEY_ARG_NAMES = (
    "model",
    "operation",
    "model_id",
    "scenario",
    "scenario_id",
    "subject",
    "mode",
    "branch_kind",
    "branch_id",
    "bus_id",
    "dataset",
    "fields",
    "filters",
    "order_by",
    "group_by",
    "aggregation",
    "comparison",
    "quantities",
    "outage_kind",
    "limit",
    "cursor",
    "page",
    "offset",
)
_SECRET_TOKENS = {
    "authorization",
    "credential",
    "credentials",
    "key",
    "passwd",
    "password",
    "secret",
    "token",
}
_INTERNAL_REF_RE = re.compile(
    r"\b(?:(?:result|evidence|context|revision|observation):[A-Za-z0-9_-]+|asset:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+):[0-9a-fA-F]{32,}\b"
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bAuthorization\s*:\s*Bearer\s+[^\s,;，；。)）]+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[^\s,;，；。)）]+", re.IGNORECASE),
    re.compile(
        r"\b(?:access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|api[_ -]?key|private[_ -]?key|secret|password|key)\s*[:=]\s*[^\s,;，；。)）]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:private[_ -]?key|api[_ -]?key|secret|password|key)\s+[^\s,;，；。)）]+",
        re.IGNORECASE,
    ),
)


def render_analysis_trajectory(
    steps: Sequence[TraceStep],
    *,
    decisions: Sequence[TraceDecision] = (),
    reuse_notes: Sequence[str] = (),
) -> list[str]:
    visible_steps = tuple(
        step for step in steps if not _is_decision_tool_capability(step.capability)
    )
    if not visible_steps and not reuse_notes:
        if steps:
            return ["未观察到可附着决策的领域仿真工具调用；决策记录详见本题详细执行轨迹。"]
        return ["未观察到与本题关联的领域工具调用。"]
    milestones = build_milestones(visible_steps, decisions=decisions)
    lines = [f"- 复用：{_clean_text(note)}" for note in reuse_notes if note.strip()]
    for ordinal, milestone in enumerate(milestones, start=1):
        duration = (
            f"，{milestone.duration_seconds:.2f} 秒"
            if milestone.duration_seconds is not None
            else ""
        )
        capabilities = "、".join(_inline_code(value) for value in milestone.capabilities)
        lines.append(
            f"{ordinal}. {milestone.title}（{capabilities}，{milestone.status}{duration}）"
        )
        lines.append(f"   {milestone.detail}")
        if milestone.decision:
            lines.append(f"   决策：{milestone.decision}")
    return lines


def build_milestones(
    steps: Sequence[TraceStep],
    *,
    decisions: Sequence[TraceDecision] = (),
) -> tuple[TrajectoryMilestone, ...]:
    narrated = tuple(_milestone_for_step(step) for step in sorted(steps, key=lambda item: item.sequence))
    with_setup = _group_adjacent_setup(narrated)
    with_retries = _group_equivalent_retries(with_setup)
    with_recovery = _annotate_recovery(with_retries)
    with_decisions = _attach_decisions(with_recovery, decisions)
    return _compress_to_density_target(with_decisions, target=6)


def _milestone_for_step(step: TraceStep) -> TrajectoryMilestone:
    title, detail, important = _describe_step(step)
    return TrajectoryMilestone(
        title=title,
        capabilities=(step.capability,),
        status=_step_status(step),
        duration_seconds=step.duration_seconds,
        detail=detail,
        important=important or not step.ok,
        step_turn_ids=(step.turn_id,) if step.turn_id is not None else (),
        step_tool_call_ids=(step.tool_call_id,) if step.tool_call_id is not None else (),
        step_sequences=(step.sequence,),
        support_refs=_refs_from_result(step.result),
        semantic_signature=_semantic_signature(step),
    )


def _group_adjacent_setup(
    milestones: Sequence[TrajectoryMilestone],
) -> tuple[TrajectoryMilestone, ...]:
    grouped: list[TrajectoryMilestone] = []
    index = 0
    while index < len(milestones):
        current = milestones[index]
        if not _is_setup_milestone(current):
            grouped.append(current)
            index += 1
            continue
        group = [current]
        index += 1
        while index < len(milestones) and _is_setup_milestone(milestones[index]):
            group.append(milestones[index])
            index += 1
        grouped.append(_combine_setup_group(group))
    return tuple(grouped)


def _is_setup_milestone(milestone: TrajectoryMilestone) -> bool:
    setup_capabilities = {
        "model.list",
        "grid_guide_open",
        "guide.open",
        "context.open",
        "context.get",
        "environment.describe",
    }
    return (
        not milestone.important
        and milestone.decision is None
        and all(capability in setup_capabilities for capability in milestone.capabilities)
    )


def _combine_setup_group(group: Sequence[TrajectoryMilestone]) -> TrajectoryMilestone:
    model = next(
        (
            _setup_model_label(milestone.detail)
            for milestone in group
            if _setup_model_label(milestone.detail) is not None
        ),
        None,
    )
    title = f"准备 {model} 仿真环境" if model is not None else "准备仿真环境"
    details: list[str] = [f"{len(group)} 次调用"]
    count_summary = next(
        (
            _setup_count_summary(milestone.detail)
            for milestone in group
            if _setup_count_summary(milestone.detail) is not None
        ),
        None,
    )
    if count_summary:
        details.append(count_summary)
    capabilities = tuple(dict.fromkeys(capability for milestone in group for capability in milestone.capabilities))
    return TrajectoryMilestone(
        title=title,
        capabilities=capabilities,
        status=_combined_status(group),
        duration_seconds=_combined_duration(group),
        detail="；".join(details),
        important=False,
        step_turn_ids=_merge_step_ids(milestone.step_turn_ids for milestone in group),
        step_tool_call_ids=_merge_step_ids(milestone.step_tool_call_ids for milestone in group),
        step_sequences=tuple(sequence for milestone in group for sequence in milestone.step_sequences),
        support_refs=_merge_step_ids(milestone.support_refs for milestone in group),
        semantic_signature="setup:" + "|".join(milestone.semantic_signature or "" for milestone in group),
    )


def _setup_model_label(detail: str) -> str | None:
    match = re.search(r"模型=([^；]+)", detail)
    if match is None:
        return None
    value = match.group(1).strip()
    if value.lower() == "ieee39":
        return "IEEE-39"
    return value


def _setup_count_summary(detail: str) -> str | None:
    matches = re.findall(r"(?:buses|bus|母线)=? ?(\d+)|(?:lines|line|线路)=? ?(\d+)|(?:transformers|trafo|变压器)=? ?(\d+)", detail)
    if not matches:
        return None
    labels = ("母线", "线路", "变压器")
    values: list[str] = []
    seen: set[str] = set()
    for groups in matches:
        for index, value in enumerate(groups):
            if not value or labels[index] in seen:
                continue
            values.append(f"{labels[index]} {value}")
            seen.add(labels[index])
    return "，".join(values) if values else None


def _group_equivalent_retries(
    milestones: Sequence[TrajectoryMilestone],
) -> tuple[TrajectoryMilestone, ...]:
    grouped: list[TrajectoryMilestone] = []
    index = 0
    while index < len(milestones):
        current = milestones[index]
        group = [current]
        index += 1
        while index < len(milestones) and _retry_signature(milestones[index]) == _retry_signature(current):
            group.append(milestones[index])
            index += 1
        grouped.append(_combine_retry_group(group) if len(group) > 1 else current)
    return tuple(grouped)


def _retry_signature(milestone: TrajectoryMilestone) -> tuple[tuple[str, ...], str, str, str, bool]:
    return (
        milestone.capabilities,
        milestone.title,
        milestone.status,
        milestone.semantic_signature or milestone.detail,
        milestone.important,
    )


def _combine_retry_group(group: Sequence[TrajectoryMilestone]) -> TrajectoryMilestone:
    first = group[0]
    return replace(
        first,
        duration_seconds=_combined_duration(group),
        detail=f"{len(group)} 次等价调用；{first.detail}",
        step_turn_ids=_merge_step_ids(milestone.step_turn_ids for milestone in group),
        step_tool_call_ids=_merge_step_ids(milestone.step_tool_call_ids for milestone in group),
        step_sequences=tuple(sequence for milestone in group for sequence in milestone.step_sequences),
        support_refs=_merge_step_ids(milestone.support_refs for milestone in group),
    )


def _annotate_recovery(
    milestones: Sequence[TrajectoryMilestone],
) -> tuple[TrajectoryMilestone, ...]:
    annotated: list[TrajectoryMilestone] = list(milestones)
    for index in range(1, len(annotated)):
        previous = annotated[index - 1]
        current = annotated[index]
        if not _is_recovery_pair(previous, current):
            continue
        changed = _changed_recovery_input(previous, current)
        if changed is None:
            continue
        annotated[index] = replace(
            current,
            detail=f"{current.detail}；恢复：改用 {changed}",
            important=True,
        )
    return tuple(annotated)


def _is_recovery_pair(
    previous: TrajectoryMilestone,
    current: TrajectoryMilestone,
) -> bool:
    return (
        previous.status == "返回受限/错误"
        and current.status == "完成"
        and previous.capabilities == current.capabilities
        and _dataset_from_title(previous.title) == _dataset_from_title(current.title)
    )


def _changed_recovery_input(
    previous: TrajectoryMilestone,
    current: TrajectoryMilestone,
) -> str | None:
    previous_fields = _fields_from_detail(previous.detail)
    current_fields = _fields_from_detail(current.detail)
    if current_fields and current_fields != previous_fields:
        return current_fields
    return None


def _dataset_from_title(title: str) -> str | None:
    match = re.search(r"查询 `([^`]+)`", title)
    return match.group(1) if match is not None else None


def _fields_from_detail(detail: str) -> str | None:
    match = re.search(r"字段 ([^；]+)", detail)
    return match.group(1).strip() if match is not None else None


def _attach_decisions(
    milestones: Sequence[TrajectoryMilestone],
    decisions: Sequence[TraceDecision],
) -> tuple[TrajectoryMilestone, ...]:
    attached = list(milestones)
    used: set[int] = set()
    for decision_index, decision in enumerate(decisions):
        target_index = _decision_target(attached, decision)
        if target_index is None or decision_index in used:
            continue
        attached[target_index] = _attach_decision(attached[target_index], decision)
        used.add(decision_index)
    return tuple(attached)


def _decision_target(
    milestones: Sequence[TrajectoryMilestone],
    decision: TraceDecision,
) -> int | None:
    if decision.support_refs:
        support_refs = set(decision.support_refs)
        for index, milestone in enumerate(milestones):
            if (
                not _is_decision_tool_milestone(milestone)
                and support_refs.intersection(milestone.support_refs)
            ):
                return index
        return None
    if decision.tool_call_id is not None:
        for index, milestone in enumerate(milestones):
            if (
                not _is_decision_tool_milestone(milestone)
                and decision.tool_call_id in milestone.step_tool_call_ids
            ):
                return index
    return None


def _is_decision_tool_milestone(milestone: TrajectoryMilestone) -> bool:
    return any(_is_decision_tool_capability(capability) for capability in milestone.capabilities)


def _is_decision_tool_capability(capability: str) -> bool:
    return capability in {"grid_record_decision", "business.decision.declared"}


def _attach_decision(
    milestone: TrajectoryMilestone,
    decision: TraceDecision,
) -> TrajectoryMilestone:
    decision_text = _clean_text(decision.decision)
    next_action = _clean_text(decision.next_action)
    text = decision_text
    if next_action:
        text = f"{text}；下一步：{next_action}" if text else f"下一步：{next_action}"
    if not text:
        return milestone
    combined = f"{milestone.decision}；{text}" if milestone.decision else text
    return replace(milestone, decision=combined, important=True)


def _compress_to_density_target(
    milestones: Sequence[TrajectoryMilestone],
    *,
    target: int,
) -> tuple[TrajectoryMilestone, ...]:
    if len(milestones) <= target:
        return tuple(milestones)
    protected = [milestone for milestone in milestones if not _is_compressible_low_information(milestone)]
    if len(protected) >= target:
        return tuple(protected)
    keep_low_information = max(0, target - len(protected))
    kept_low = 0
    omitted: list[TrajectoryMilestone] = []
    result: list[TrajectoryMilestone] = []
    for milestone in milestones:
        if _is_compressible_low_information(milestone):
            if kept_low < keep_low_information:
                result.append(milestone)
                kept_low += 1
            else:
                omitted.append(milestone)
            continue
        result.append(milestone)
    if omitted:
        summary = _omission_summary(omitted)
        for index in range(len(result) - 1, -1, -1):
            if _is_compressible_low_information(result[index]):
                result[index] = replace(
                    result[index],
                    detail=f"{result[index].detail}；{summary}",
                )
                break
    return tuple(result)


def _is_compressible_low_information(milestone: TrajectoryMilestone) -> bool:
    if milestone.important or milestone.decision is not None:
        return False
    low_information_capabilities = {
        "model.list",
        "grid_guide_open",
        "guide.open",
        "context.open",
        "context.get",
        "environment.describe",
        "model.dataset.describe",
    }
    if all(capability in low_information_capabilities for capability in milestone.capabilities):
        return True
    return milestone.title in {"准备仿真环境"} or milestone.title.startswith("准备 ")


def _omission_summary(milestones: Sequence[TrajectoryMilestone]) -> str:
    labels = {_compact_label(milestone) for milestone in milestones}
    label = labels.pop() if len(labels) == 1 else "低信息核对"
    return f"其余 {len(milestones)} 次{label}"


def _compact_label(milestone: TrajectoryMilestone) -> str:
    if "model.dataset.describe" in milestone.capabilities:
        return "数据集结构核对"
    if _is_setup_milestone(milestone):
        return "环境准备"
    return "低信息核对"


def _combined_status(milestones: Sequence[TrajectoryMilestone]) -> str:
    if any(milestone.status == "返回受限/错误" for milestone in milestones):
        return "返回受限/错误"
    if any(milestone.status == "未收敛" for milestone in milestones):
        return "未收敛"
    if any(milestone.status == "部分完成" for milestone in milestones):
        return "部分完成"
    return "完成"


def _combined_duration(milestones: Sequence[TrajectoryMilestone]) -> float | None:
    durations = [milestone.duration_seconds for milestone in milestones if milestone.duration_seconds is not None]
    return sum(durations) if durations else None


def _merge_step_ids(values: Iterable[Sequence[str]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in values for item in group))


def _step_status(step: TraceStep) -> str:
    if not step.ok:
        return "返回受限/错误"
    status = step.result.get("status")
    if status == "partial":
        return "部分完成"
    if status in {"failed", "error"}:
        return "返回受限/错误"
    if step.result.get("converged") is False:
        return "未收敛"
    return "完成"


def _describe_step(step: TraceStep) -> tuple[str, str, bool]:
    if step.capability == "context.open":
        return _describe_context_open(step)
    if step.capability == "topology.branch.endpoints.get":
        return _describe_branch_endpoints(step)
    if step.capability == "analysis.powerflow.ac.run":
        return _describe_powerflow(step)
    if step.capability == "result.branches.rank":
        return _describe_branch_rank(step)
    if step.capability == "model.dataset.query":
        return _describe_dataset_query(step)
    if step.capability == "analysis.result.violations.evaluate":
        return _describe_violations(step)
    if step.capability == "analysis.contingency.n_minus_one.run":
        return _describe_contingency(step)
    if step.capability == "grid_submit_answer":
        return "提交本题回答", _fallback_detail(step), False
    labels = {
        "environment.describe": "核对仿真器协议和已发布能力",
        "model.list": "确认可用的已注册网络模型",
        "context.get": "读取已打开的仿真环境上下文",
        "model.element.get": "定位问题涉及的网络元件",
        "model.dataset.describe": "核对数据集结构",
        "model.constraints.describe": "读取活动模型内定义的约束",
        "topology.components.get": "核查网络拓扑连通性",
        "evidence.get": "读取已持久化的仿真证据",
        "grid_guide_open": "读取已发布的领域操作指南",
    }
    return labels.get(step.capability, "调用已发布的领域能力"), _fallback_detail(step), False


def _describe_context_open(step: TraceStep) -> tuple[str, str, bool]:
    model = _first_scalar(step.result, ("model", "model_id", "network"))
    source = _first_scalar(step.result, ("source", "dataset"))
    parts = []
    if model is not None:
        parts.append(f"模型={_safe_scalar(model)}")
    if source is not None:
        parts.append(f"来源={_safe_scalar(source)}")
    counts = step.result.get("counts")
    if isinstance(counts, Mapping):
        count_parts = []
        for key, label in (("buses", "母线"), ("bus", "母线"), ("lines", "线路"), ("line", "线路"), ("transformers", "变压器"), ("trafo", "变压器")):
            value = _safe_scalar(counts.get(key))
            if value is not None and not any(item.startswith(label) for item in count_parts):
                count_parts.append(f"{label} {value}")
        if count_parts:
            parts.append("，".join(count_parts))
    return (
        "打开只读网络仿真环境上下文",
        "；".join(parts) if parts else _fallback_detail(step),
        False,
    )


def _describe_branch_endpoints(step: TraceStep) -> tuple[str, str, bool]:
    kind = _safe_scalar(step.args.get("branch_kind", "branch"))
    branch_id = _safe_scalar(step.args.get("branch_id"))
    subject = _branch_label(kind, branch_id)
    from_bus = _safe_scalar(step.result.get("from_bus"))
    to_bus = _safe_scalar(step.result.get("to_bus"))
    detail = (
        f"母线 {from_bus} → 母线 {to_bus}"
        if from_bus is not None and to_bus is not None
        else _fallback_detail(step)
    )
    return f"核查{subject}两端母线", detail, True


def _describe_powerflow(step: TraceStep) -> tuple[str, str, bool]:
    title = "运行交流潮流计算"
    parts: list[str] = []
    if step.result.get("converged") is True:
        parts.append("收敛")
    elif step.result.get("converged") is False:
        parts.append("未收敛")
    message = _safe_scalar(step.result.get("message"))
    if message is not None:
        parts.append(message)
    loss = step.result.get("total_active_loss")
    if isinstance(loss, Mapping):
        value = _safe_scalar(loss.get("value"))
        unit = _safe_scalar(loss.get("unit", "MW"))
        if value is not None:
            parts.append(f"有功网损 {value} {unit or 'MW'}")
    return title, "；".join(parts) if parts else _fallback_detail(step), True


def _describe_dataset_query(step: TraceStep) -> tuple[str, str, bool]:
    dataset = _safe_scalar(step.args.get("dataset")) or _safe_scalar(step.result.get("dataset"))
    title = f"查询 {_inline_code(dataset)}" if dataset else "查询网络模型数据"
    parts: list[str] = []
    for key in ("model", "model_id", "scenario", "scenario_id", "operation", "filters", "group_by", "aggregation", "comparison"):
        summary = _material_arg_summary(key, step.args.get(key))
        if summary:
            parts.append(summary)
    fields = _fields_summary(step.args.get("fields"))
    if fields:
        parts.append(f"字段 {fields}")
    order = _order_by_summary(step.args.get("order_by"))
    if order:
        parts.append(order)
    limit = _safe_scalar(step.args.get("limit"))
    if limit is not None:
        parts.append(f"前 {limit} 项")
    row_summary = _row_summary(step.result.get("rows"))
    if row_summary:
        parts.append(row_summary)
    row_count = _safe_scalar(step.result.get("row_count"))
    if row_count is not None and row_summary is None:
        parts.append(f"返回 {row_count} 行")
    message = _safe_scalar(step.result.get("message"))
    if message is not None:
        parts.append(message)
    return title, "；".join(parts) if parts else _fallback_detail(step), True


def _describe_branch_rank(step: TraceStep) -> tuple[str, str, bool]:
    parts: list[str] = []
    metric = _safe_scalar(step.args.get("metric")) or _safe_scalar(step.result.get("metric"))
    if metric is not None:
        parts.append(f"指标 {metric}")
    limit = _safe_scalar(step.args.get("limit"))
    if limit is not None:
        parts.append(f"前 {limit} 项")
    row_summary = _row_summary(step.result.get("rows") or step.result.get("branches"))
    if row_summary:
        parts.append(row_summary)
    return (
        "按支路运行指标筛选和排序",
        "；".join(parts) if parts else _fallback_detail(step),
        True,
    )


def _describe_violations(step: TraceStep) -> tuple[str, str, bool]:
    summary = step.result.get("summary")
    summary = summary if isinstance(summary, Mapping) else step.result
    source = _safe_scalar(summary.get("constraint_source"))
    source_label = "模型约束" if source == "model" else f"{source} 约束" if source else None
    count = _safe_scalar(summary.get("violation_count"))
    parts = []
    if source_label:
        parts.append(source_label)
    if count is not None:
        parts.append(f"{count} 项越限")
    unavailable = summary.get("unavailable_quantities")
    if isinstance(unavailable, Sequence) and not isinstance(unavailable, (str, bytes, bytearray)) and unavailable:
        parts.append(f"{len(unavailable)} 项指标不可用")
    return "评估运行约束越限", "；".join(parts) if parts else _fallback_detail(step), True


def _describe_contingency(step: TraceStep) -> tuple[str, str, bool]:
    outage = _safe_scalar(step.args.get("outage_kind"))
    branch_id = _safe_scalar(step.args.get("branch_id"))
    subject = "单支路 N-1 静态安全校核" if outage == "single_branch" else "N-1 静态安全校核"
    if branch_id is not None:
        subject = f"{subject}（支路 {branch_id} 停运）"
    parts: list[str] = []
    scenarios = _safe_scalar(step.result.get("scenario_count"))
    converged = _safe_scalar(step.result.get("converged_scenarios"))
    if scenarios is not None and converged is not None:
        parts.append(f"{scenarios} 个场景，{converged} 个收敛")
    elif scenarios is not None:
        parts.append(f"{scenarios} 个场景")
    if step.result.get("status") == "partial":
        parts.append("部分完成")
    worst = _safe_scalar(step.result.get("worst_loading_percent"))
    if worst is not None:
        parts.append(f"最大负载率 {worst}%")
    return f"执行{subject}", "；".join(parts) if parts else _fallback_detail(step), True


def _fallback_detail(step: TraceStep) -> str:
    args = _scalar_items(step.args, _KEY_ARG_NAMES, limit=4)
    result = _scalar_items(step.result, tuple(step.result.keys()), limit=4)
    parts = []
    if args:
        parts.append("输入：" + "，".join(args))
    if result:
        parts.append("结果：" + "，".join(result))
    return "；".join(parts) if parts else "输入和结果详见本题详细执行轨迹。"


def _semantic_signature(step: TraceStep) -> str:
    args = {
        key: _signature_value(step.args[key])
        for key in _KEY_ARG_NAMES
        if key in step.args and not _is_internal_or_secret_field(key)
    }
    result_shape = {
        key: _signature_value(step.result[key])
        for key in ("status", "code", "converged", "row_count", "field_count", "scenario_count", "converged_scenarios")
        if key in step.result and not _is_internal_or_secret_field(key)
    }
    rows = step.result.get("rows")
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
        result_shape["rows"] = _signature_value(tuple(rows[:2]))
    return f"{step.capability}|ok={step.ok}|args={args}|result={result_shape}"


def _signature_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _clean_text(str(value)) if isinstance(value, str) else value
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _signature_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_internal_or_secret_field(str(key))
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_signature_value(item) for item in value)
    return _clean_text(str(value))


def _refs_from_result(result: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []

    def collect(value: object, *, key: str | None = None) -> None:
        if isinstance(value, str):
            if (key is not None and (key.endswith("_ref") or key.endswith("_refs"))) or _INTERNAL_REF_RE.search(value):
                refs.append(value)
            return
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                collect(nested_value, key=str(nested_key))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                collect(item, key=key)

    collect(result)
    return tuple(dict.fromkeys(refs))


def _scalar_items(
    values: Mapping[str, Any],
    keys: Sequence[str],
    *,
    limit: int,
) -> list[str]:
    items: list[str] = []
    for key in keys:
        if key not in values or _is_internal_or_secret_field(key):
            continue
        formatted = _format_value(values[key])
        if formatted is None:
            continue
        items.append(f"{_clean_label(key)}={formatted}")
        if len(items) >= limit:
            break
    return items


def _material_arg_summary(key: str, value: object) -> str | None:
    formatted = _format_material_value(value)
    if formatted is None:
        return None
    return f"{_clean_label(key)}={formatted}"


def _format_material_value(value: object) -> str | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _safe_scalar(value)
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:4]:
            if _is_internal_or_secret_field(str(key)):
                continue
            formatted = _format_material_value(item)
            if formatted is not None:
                parts.append(f"{_clean_label(str(key))}={formatted}")
        return ",".join(parts) if parts else None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        visible: list[str] = []
        for item in value[:4]:
            formatted = _format_material_value(item)
            if formatted is not None:
                visible.append(formatted)
        return "、".join(visible) if visible else None
    return _clean_text(str(value))


def _format_value(value: Any) -> str | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _safe_scalar(value)
    if isinstance(value, Mapping):
        return f"{len(value)} 项"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return f"{len(value)} 项"
    return _clean_text(str(value))


def _order_by_summary(value: object) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    parts: list[str] = []
    for item in value[:2]:
        if not isinstance(item, Mapping):
            continue
        field = _safe_scalar(item.get("field"))
        direction = _direction_label(_safe_scalar(item.get("direction")))
        if field is not None:
            parts.append(f"{field} {direction}".rstrip())
    return "、".join(parts) if parts else None


def _fields_summary(value: object) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    parts = [_safe_scalar(item) for item in value[:4]]
    visible = [item for item in parts if item is not None]
    return "、".join(visible) if visible else None


def _direction_label(value: str | None) -> str:
    if value == "desc":
        return "降序"
    if value == "asc":
        return "升序"
    return value or ""


def _row_summary(value: object) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)) or not value:
        return None
    first = value[0]
    if not isinstance(first, Mapping):
        return None
    branch = _first_present_scalar(first, ("line", "branch", "branch_id"))
    loading = _safe_scalar(first.get("loading_percent"))
    if branch is not None and loading is not None:
        return f"线路 {branch}：{loading}%"
    bus = _first_present_scalar(first, ("bus", "bus_id"))
    vm = _safe_scalar(first.get("vm_pu"))
    if bus is not None and vm is not None:
        return f"母线 {bus}：{vm} p.u."
    visible = _scalar_items(first, tuple(str(key) for key in first.keys()), limit=2)
    return "，".join(visible) if visible else None


def _first_scalar(values: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        if key in values:
            return _safe_scalar(values[key])
    return None


def _first_present_scalar(values: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        if key in values:
            scalar = _safe_scalar(values[key])
            if scalar is not None:
                return scalar
    return None


def _safe_scalar(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float, bool)):
        return None
    text = f"{value}"
    text = _clean_text(text)
    return text if text else None


def _clean_text(value: str) -> str:
    cleaned = _INTERNAL_REF_RE.sub("", value)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        cleaned = pattern.sub("[已遮蔽敏感值]", cleaned)
    cleaned = _normalize_visible_whitespace(cleaned)
    cleaned = _neutralize_markdown_html(cleaned)
    return cleaned.strip()


def _clean_label(value: str) -> str:
    return _clean_text(value)


def _inline_code(value: str) -> str:
    return f"`{_clean_text(value)}`"


def _normalize_visible_whitespace(value: str) -> str:
    return " ".join(value.split())


def _neutralize_markdown_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("`", "｀")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )


def _branch_label(kind: str | None, branch_id: str | None) -> str:
    labels = {"line": "线路", "trafo": "变压器", "branch": "支路"}
    label = labels.get(kind or "branch", kind or "支路")
    return f"{label} {branch_id} " if branch_id is not None else f"{label}"


def _is_internal_or_secret_field(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("_ref") or lowered.endswith("_refs"):
        return True
    tokens = _field_name_tokens(key)
    if any(token in _SECRET_TOKENS for token in tokens):
        return True
    pairs = set(zip(tokens, tokens[1:], strict=False))
    if ("api", "key") in pairs or ("private", "key") in pairs:
        return True
    compact = "".join(tokens)
    return compact.endswith("apikey") or compact.endswith("privatekey")


def _field_name_tokens(key: str) -> tuple[str, ...]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return tuple(
        token
        for token in re.split(r"[^A-Za-z0-9]+", separated.lower())
        if token
    )
