from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
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
    "分析摘要",
    "运行环境",
    "仿真基线",
    "分析执行上下文",
    "结果依赖关系",
    "指令执行时间线",
    "未解决限制",
    "复核工件",
)


def render_analysis_report(
    *,
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    environment: Mapping[str, str],
) -> str:
    """Render the operator-facing report from finalized structured context.

    The submitted answer body is loaded from the accepted per-turn answer JSON
    registered in the context and is inserted without humanizing or rewriting.
    """
    events = _read_context_events(workspace.context_events_path)
    turn_revisions = _turn_revision_ranges(events)
    lines = ["# 分析报告", ""]

    _append_section(lines, "分析摘要", _render_summary(context))
    _append_section(lines, "运行环境", _render_environment(context, environment))
    _append_section(lines, "仿真基线", _render_baselines(context))
    _append_section(lines, "分析执行上下文", _render_final_context(context, workspace))
    _append_section(lines, "结果依赖关系", _render_dependencies(context))
    _append_section(lines, "指令执行时间线", _render_timeline(context, workspace, turn_revisions))
    limitation_body = _render_limitations(context)
    if limitation_body:
        _append_section(lines, "未解决限制", limitation_body)
    _append_section(lines, "复核工件", _render_forensic_artifacts(workspace))

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


def _render_baselines(context: AnalysisContext) -> list[str]:
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
                    _link(baseline.path, baseline.path),
                )
            )
            + " |"
        )
    if omitted:
        rows.append(f"补充基线 {omitted} 项与上表来源相同，未重复展开。")
    return rows


def _render_final_context(context: AnalysisContext, workspace: AnalysisWorkspace) -> list[str]:
    return [
        f"- 上下文文件：{_link(workspace.context_snapshot_path.relative_to(workspace.root_path), 'context/analysis-context.json')}",
        f"- 事件账本：{_link(workspace.context_events_path.relative_to(workspace.root_path), 'context/context-events.jsonl')}",
        f"- 当前活动回合：{context.current_turn.turn_id if context.current_turn else '无'}",
        f"- 已注册结果：{len(context.results)}；证据：{len(context.evidence)}；已验证事实：{len(context.verified_facts)}；诊断：{len(context.diagnostics)}",
    ]


def _render_dependencies(context: AnalysisContext) -> list[str]:
    rows = ["| 引用 | 类型 | 生产回合 | 依赖 | 工件 |", "| --- | --- | --- | --- | --- |"]
    for result in context.results.values():
        rows.append(
            _dependency_row(
                ref=result.result_ref,
                kind="result",
                turn_id=result.turn_id,
                deps=[result.revision_ref, *result.evidence_refs],
                path=result.path,
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
) -> str:
    return (
        "| "
        + " | ".join(
            (
                f"`{_md(ref)}`",
                _md(kind),
                _md(turn_id or "全局"),
                "<br>".join(f"`{_md(dep)}`" for dep in deps) if deps else "—",
                _link(path, path),
            )
        )
        + " |"
    )


def _render_timeline(
    context: AnalysisContext,
    workspace: AnalysisWorkspace,
    turn_revisions: Mapping[str, tuple[int, int]],
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
        start_revision, end_revision = turn_revisions.get(turn.turn_id, (0, context.revision))
        lines.extend(
            [
                f"### {turn.ordinal}. {turn.instruction}",
                "",
                f"- turn_id：`{turn.turn_id}`；状态：{turn.status}；上下文版本：{start_revision} → {end_revision}",
                f"- 耗时：{turn.duration_seconds:.2f} 秒" if turn.duration_seconds is not None else "- 耗时：未记录",
                f"- 接受答案：{_answer_link_or_label(turn)}",
                "- answer_output：",
                "",
                _accepted_answer_text(turn, workspace, limitations_by_turn.get(turn.turn_id, ())),
                "",
                f"- 复用前序结果：{_refs(turn.consumed_refs)}",
                f"- 新增工件：{_refs(turn.produced_refs)}",
            ]
        )
        diagnostics = diagnostics_by_turn.get(turn.turn_id, [])
        if diagnostics:
            lines.extend(["- 审计诊断："])
            for diagnostic in diagnostics:
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


def _render_forensic_artifacts(workspace: AnalysisWorkspace) -> list[str]:
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
        lines.append(f"- {_link(relative, str(relative))}")
    return lines


def _accepted_answer_text(
    turn: TurnRecord,
    workspace: AnalysisWorkspace,
    limitations: Sequence[LimitationRecord],
) -> str:
    if turn.answer_path:
        answer_path = _workspace_path(workspace, turn.answer_path)
        document = _read_json(answer_path)
        if isinstance(document, Mapping) and isinstance(document.get("answer_output"), str):
            return str(document["answer_output"])
        return "接受答案文件不可读；请复核注册路径。"
    if limitations:
        return "执行限制 / execution limitation: " + limitations[0].message
    return "本回合未注册接受答案。"


def _answer_link_or_label(turn: TurnRecord) -> str:
    if not turn.answer_path:
        return "无接受答案文件"
    return _link(turn.answer_path, turn.answer_path)


def _read_context_events(path: Path) -> tuple[AnalysisContextEvent, ...]:
    if not path.is_file():
        return ()
    events: list[AnalysisContextEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(AnalysisContextEvent.model_validate_json(line))
        except (ValueError, ValidationError):
            continue
    return tuple(events)


def _turn_revision_ranges(events: Sequence[AnalysisContextEvent]) -> dict[str, tuple[int, int]]:
    ranges: dict[str, list[int]] = {}
    for event in events:
        if not event.turn_id:
            continue
        if event.event_type == "turn.started":
            ranges[event.turn_id] = [event.next_revision, event.next_revision]
        elif event.turn_id in ranges:
            ranges[event.turn_id][1] = max(ranges[event.turn_id][1], event.next_revision)
    return {turn_id: (values[0], values[1]) for turn_id, values in ranges.items()}


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _workspace_path(workspace: AnalysisWorkspace, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        try:
            path.relative_to(workspace.root_path)
        except ValueError:
            return workspace.root_path / path.name
        return path
    return workspace.root_path / path


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
