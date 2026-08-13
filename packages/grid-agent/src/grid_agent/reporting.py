from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BatchRecord:
    ordinal: int
    question: str
    question_id: str
    answer_output: str
    status: str
    duration_seconds: float
    run_path: str | None
    steps: tuple[tuple[str, float], ...]
    evidence_refs: tuple[str, ...]
    result_refs: tuple[str, ...]
    error: str | None


def load_questions(path: Path) -> tuple[str, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    questions = tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    if not questions:
        raise ValueError(f"question file contains no questions: {path}")
    return questions


def render_markdown(
    *,
    batch_id: str,
    source_name: str,
    environment: Mapping[str, str],
    records: Sequence[BatchRecord],
) -> str:
    counts = {status: sum(record.status == status for record in records) for status in ("success", "limited", "failed")}
    lines = [
        "# 系统仿真分析报告",
        "",
        f"- 批次编号：`{batch_id}`",
        f"- 问题文件：`{source_name}`",
        f"- 总问题数：{len(records)}；成功：{counts['success']}；受限：{counts['limited']}；失败：{counts['failed']}",
        "",
        "## 仿真环境",
        "",
    ]
    lines.extend(f"- {label}：`{value}`" for label, value in environment.items())
    for record in records:
        lines.extend(
            [
                "",
                f"## 问题 {record.ordinal}",
                "",
                f"- 问题：{record.question}",
                f"- question_id：`{record.question_id}`",
                f"- 执行状态：{_status_label(record.status)}",
                f"- 总时长：{record.duration_seconds:.2f} 秒",
                f"- 运行目录：`{record.run_path}`" if record.run_path else "- 运行目录：未创建（离线知识或启动前失败）",
                "",
                "### 任务拆解（基于实际执行）",
                "",
            ]
        )
        if record.steps:
            lines.extend(f"{index}. `{name}`：{seconds:.2f} 秒" for index, (name, seconds) in enumerate(record.steps, start=1))
        else:
            lines.append("未观察到已完成的领域工具调用。")
        lines.extend(["", "### 证据来源", ""])
        if record.evidence_refs or record.result_refs:
            lines.extend(f"- 证据引用：`{reference}`" for reference in record.evidence_refs)
            lines.extend(f"- 仿真结果引用：`{reference}`" for reference in record.result_refs)
        else:
            lines.append("本题没有可引用的仿真证据。")
        lines.extend(["", "### 回答", "", record.answer_output])
        if record.error:
            lines.extend(["", "### 受限或失败原因", "", record.error])
    return "\n".join(lines) + "\n"


def write_jsonl(path: Path, records: Sequence[BatchRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"question_id": record.question_id, "answer_output": record.answer_output}, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def read_run_observations(run_path: Path) -> tuple[tuple[tuple[str, float], ...], tuple[str, ...], tuple[str, ...]]:
    events_path = run_path / "events.jsonl"
    if not events_path.is_file():
        return (), (), ()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    steps: list[tuple[str, float]] = []
    evidence_refs: list[str] = []
    result_refs: list[str] = []
    starts: list[tuple[str, str]] = []
    for event in events:
        payload = _payload(event)
        if not isinstance(payload, Mapping):
            continue
        event_type = payload.get("type", payload.get("event"))
        capability = payload.get("capability")
        if event_type == "tool_execution_start":
            tool_name = payload.get("toolName")
            if isinstance(tool_name, str):
                starts.append((tool_name, str(event.get("timestamp", ""))))
        if event_type != "tool_result" or not isinstance(capability, str):
            continue
        seconds = _seconds_between(_take_start_timestamp(starts, capability), str(event.get("timestamp", "")))
        steps.append((capability, seconds))
        _add_refs(payload.get("evidence_refs"), evidence_refs)
        result = payload.get("result")
        if isinstance(result, Mapping):
            _add_refs(result.get("evidence_refs"), evidence_refs)
            _add_refs([result.get("evidence_ref")], evidence_refs)
            _add_refs([result.get("result_ref")], result_refs)
    return tuple(steps), tuple(dict.fromkeys(evidence_refs)), tuple(dict.fromkeys(result_refs))


def _payload(event: Mapping[str, Any]) -> object:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else event


def _add_refs(value: object, destination: list[str]) -> None:
    if isinstance(value, list):
        destination.extend(item for item in value if isinstance(item, str))


def _seconds_between(start: str, end: str) -> float:
    from datetime import datetime

    try:
        return max(0.0, (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        return 0.0


def _take_start_timestamp(starts: list[tuple[str, str]], capability: str) -> str:
    expected = capability.removesuffix(".get")
    for index, (tool_name, timestamp) in enumerate(starts):
        normalized = tool_name.removeprefix("grid_").replace("_", ".")
        if normalized == expected:
            starts.pop(index)
            return timestamp
    return ""


def _status_label(status: str) -> str:
    return {"success": "成功", "limited": "受限", "failed": "失败"}.get(status, status)
