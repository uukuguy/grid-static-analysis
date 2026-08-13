from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from grid_agent.analysis.models import (
    AnalysisContext,
    AnalysisContextEvent,
    BaselineRecord,
    DiagnosticRecord,
    LimitationRecord,
    TurnRecord,
)
from grid_agent.analysis.workspace import AnalysisWorkspace


REPORT_SECTIONS = (
    "结论总览",
    "逐题分析",
    "审计附录",
)


def render_analysis_report(
    *,
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    environment: Mapping[str, str],
) -> str:
    """Render the operator-facing report from finalized structured context.

    Accepted answers and raw forensic data remain in their registered files.
    The reader-facing body replaces opaque internal references with a short
    provenance marker; the complete values remain in the collapsed appendix.
    """
    diagnostics: list[str] = []
    ledger = _read_context_events(workspace.context_events_path)
    diagnostics.extend(ledger.diagnostics)
    turn_revisions = _turn_revision_ranges(ledger.events, context.turns)
    diagnostics.extend(turn_revisions.diagnostics)
    lines = ["# 分析报告", ""]

    _append_section(lines, "结论总览", _render_reader_summary(context, workspace, diagnostics))
    _append_section(lines, "逐题分析", _render_reader_turns(context, workspace, ledger.events, diagnostics))
    _append_section(lines, "审计附录", _render_audit_appendix(context, workspace, environment, diagnostics))

    return "\n".join(lines).rstrip() + "\n"


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
    return _redact_internal_refs(message)


def _redact_internal_refs(value: str) -> str:
    return re.sub(
        r"(?:context|revision|result|evidence|observation):sha256:[0-9a-f]{4,64}(?:\.\.\.)?|asset:[^\s:]+:sha256:[0-9a-f]{4,64}",
        "〔可追溯引用〕",
        value,
    )


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
        return "执行限制 / execution limitation: " + limitations[0].message
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
    safe_label = label if label == resolved.relative else resolved.relative
    return _link(resolved.relative, safe_label)


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
