from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TrajectoryMilestone:
    title: str
    capabilities: tuple[str, ...]
    status: str
    duration_seconds: float | None
    detail: str
    decision: str | None = None
    important: bool = False


_KEY_ARG_NAMES = (
    "model",
    "operation",
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
)
_SECRET_TOKENS = {
    "authorization",
    "credential",
    "credentials",
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
        r"\b(?:access[_ -]?token|refresh[_ -]?token|id[_ -]?token|token|api[_ -]?key|private[_ -]?key|secret|password)\s*[:=]\s*[^\s,;，；。)）]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:private[_ -]?key|api[_ -]?key|secret|password)\s+[^\s,;，；。)）]+",
        re.IGNORECASE,
    ),
)


def render_analysis_trajectory(
    steps: Sequence[TraceStep],
    *,
    decisions: Sequence[TraceDecision] = (),
    reuse_notes: Sequence[str] = (),
) -> list[str]:
    if not steps and not reuse_notes:
        return ["未观察到与本题关联的领域工具调用。"]
    milestones = build_milestones(steps, decisions=decisions)
    lines = [f"- 复用：{note}" for note in reuse_notes if note.strip()]
    for ordinal, milestone in enumerate(milestones, start=1):
        duration = (
            f"，{milestone.duration_seconds:.2f} 秒"
            if milestone.duration_seconds is not None
            else ""
        )
        capabilities = "、".join(f"`{value}`" for value in milestone.capabilities)
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
    decision_by_call = {
        decision.tool_call_id: decision
        for decision in decisions
        if decision.tool_call_id is not None
    }
    decision_by_turn = {
        decision.turn_id: decision
        for decision in decisions
        if decision.turn_id is not None
    }
    milestones = tuple(
        _attach_decision(_milestone_for_step(step), _decision_for_step(step, decision_by_call, decision_by_turn))
        for step in sorted(steps, key=lambda item: item.sequence)
    )
    return milestones


def _decision_for_step(
    step: TraceStep,
    decision_by_call: Mapping[str, TraceDecision],
    decision_by_turn: Mapping[str, TraceDecision],
) -> TraceDecision | None:
    if step.tool_call_id is not None and step.tool_call_id in decision_by_call:
        return decision_by_call[step.tool_call_id]
    if step.turn_id is not None and step.turn_id in decision_by_turn:
        return decision_by_turn[step.turn_id]
    return None


def _attach_decision(
    milestone: TrajectoryMilestone,
    decision: TraceDecision | None,
) -> TrajectoryMilestone:
    if decision is None:
        return milestone
    parts = [
        _clean_text(decision.intent),
        _clean_text(decision.decision),
        _clean_text(decision.next_action),
    ]
    text = "；".join(part for part in parts if part)
    if not text:
        return milestone
    return TrajectoryMilestone(
        milestone.title,
        milestone.capabilities,
        milestone.status,
        milestone.duration_seconds,
        milestone.detail,
        text,
        True,
    )


def _milestone_for_step(step: TraceStep) -> TrajectoryMilestone:
    title, detail, important = _describe_step(step)
    return TrajectoryMilestone(
        title=title,
        capabilities=(step.capability,),
        status=_step_status(step),
        duration_seconds=step.duration_seconds,
        detail=detail,
        important=important or not step.ok,
    )


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
        "model.dataset.describe": "核对可查询的数据集与字段",
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
    loss = step.result.get("total_active_loss")
    if isinstance(loss, Mapping):
        value = _safe_scalar(loss.get("value"))
        unit = _safe_scalar(loss.get("unit", "MW"))
        if value is not None:
            parts.append(f"有功网损 {value} {unit or 'MW'}")
    return title, "；".join(parts) if parts else _fallback_detail(step), True


def _describe_dataset_query(step: TraceStep) -> tuple[str, str, bool]:
    dataset = _safe_scalar(step.args.get("dataset")) or _safe_scalar(step.result.get("dataset"))
    title = f"查询 `{dataset}`" if dataset else "查询网络模型数据"
    parts: list[str] = []
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
        items.append(f"{key}={formatted}")
        if len(items) >= limit:
            break
    return items


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
    return cleaned.strip()


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
