# Readable Agent Analysis Trajectory Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore answer-first readable analysis reports while rendering a compact, diagnostic, externally observable agent trajectory from recorded tool inputs, simulator results, lineage, failures, and optional decisions.

**Architecture:** `analysis/report.py` continues to own report assembly, workspace links, context/evidence projection, and tolerant trace I/O. A new pure `analysis/report_trajectory.py` module owns capability-specific step narration, decision attachment, setup/retry compaction, and the six-milestone density target. The main report never expands raw tool-result JSON; complete inputs and outputs remain in each turn's existing `trace.md`.

**Tech Stack:** Python 3.14, Pydantic analysis models, native JSONL trajectory events, pytest, Pyright, Markdown reports.

## Global Constraints

- CLI stdout remains exactly one JSON object containing `question_id` and `answer_output`; diagnostics stay on stderr.
- Numerical and network-specific claims come only from recorded `gridctl` results using `grid-capability` protocol `1.0` and pandapower `3.4.0`.
- Pi/LLM uses only project-defined grid tools and `grid_guide_open`; this change must not reintroduce model-owned answer submission or mandatory narration calls.
- The report exposes observable actions, inputs, results, lineage, failures, and recorded decisions, never private chain-of-thought or invented motives.
- The main report contains no expanded tool-result JSON; raw detail remains linked through `turns/NNN/trace.md` and tool-result artifacts.
- Internal references, paths, nonces, hashes, credentials, authorization data, keys, and token-shaped fields remain absent from reader-facing prose.
- Failed turns retain successful simulator milestones, concrete failure reasons, and recovery actions.
- Target at most six visible milestones and approximately 20–25 trajectory lines per question, but never hide distinct failures, partial/non-converged outcomes, principal results, violations, rankings, contingency outcomes, decisions, or recoveries.
- Preserve user-owned dirty files and ignored `runs/`; do not run `make validate-provider`.

## File Structure

- Create `packages/grid-agent/src/grid_agent/analysis/report_trajectory.py`: pure trajectory types, capability-specific semantic projection, decision attachment, compaction, and Markdown rendering.
- Create `packages/grid-agent/tests/analysis/test_report_trajectory.py`: focused unit tests for semantic step descriptions, key inputs/results, decisions, recovery, compaction, density, fallback bounding, and redaction.
- Modify `packages/grid-agent/src/grid_agent/analysis/report.py`: restore answer-first/context-first assembly, parse optional decision events, call the new trajectory renderer, retain tolerant detailed-trace generation.
- Modify `packages/grid-agent/tests/analysis/test_report.py`: report-level ordering, context restoration, failed-turn, evidence-link, and no-expanded-JSON contracts.
- Modify `packages/grid-agent/tests/e2e/test_continuous_analysis.py`: end-to-end section order, environment context, compact trajectory, and detailed-trace link assertions.
- Modify `docs/architecture/analysis-context.md`: replace the superseded result-first report description with answer-first observable trajectory semantics.
- Modify `docs/status/CURRENT-STATE.md`: update the structural reporting summary only.
- Modify `docs/status/DECISIONS.md`: append the superseding report-presentation decision and link the approved specification and this plan.

---

### Task 1: Restore answer-first report structure and simulation context

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py:81-133`
- Modify: `packages/grid-agent/tests/analysis/test_report.py:31-145`
- Modify: `packages/grid-agent/tests/e2e/test_continuous_analysis.py:150-180`

**Interfaces:**
- Consumes: existing `_render_turn_context(...)`, `_render_trace_steps(...)`, `_render_turn_evidence(...)`, and per-turn `trace.md` links.
- Produces: the stable per-question section contract `回答 → 仿真环境上下文 → 智能体分析轨迹 → 执行状态与证据` used by all later tasks.

- [ ] **Step 1: Replace result-first report assertions with answer-first/context-restored assertions**

Update the report tests to extract one turn and assert the exact section order and absence of expanded JSON in the trajectory section:

```python
def test_report_puts_answer_first_and_restores_simulation_context(
    report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    first_turn = report.split("## 2.", maxsplit=1)[0]
    answer_at = first_turn.index("### 回答")
    context_at = first_turn.index("### 仿真环境上下文")
    trajectory_at = first_turn.index("### 智能体分析轨迹")
    evidence_at = first_turn.index("### 执行状态与证据")

    assert answer_at < context_at < trajectory_at < evidence_at
    assert report_fixture.answer_text in first_turn[answer_at:context_at]
    assert "活动模型：IEEE-39" in first_turn[context_at:trajectory_at]
    assert "母线电压约束：0.94–1.06 p.u.（模型数据）" in first_turn[context_at:trajectory_at]
    assert "```json" not in first_turn[trajectory_at:evidence_at]
    assert "turns/001/trace.md" in first_turn[evidence_at:]
```

Update the failed-turn test so the answer placeholder appears before restored context and successful steps:

```python
def test_failed_turn_keeps_answer_first_context_and_successful_trajectory(
    failed_report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=failed_report_fixture.context,
        workspace=failed_report_fixture.workspace,
        environment={},
    )
    failed_turn = report.split("## 2. 失败回合", maxsplit=1)[1]
    assert failed_turn.index("模型未返回可接受的最终回答。") < failed_turn.index(
        "### 仿真环境上下文"
    )
    assert failed_turn.index("### 仿真环境上下文") < failed_turn.index(
        "### 智能体分析轨迹"
    )
    assert "核查支路两端母线" in failed_turn
    assert "状态：未完成" in failed_turn
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report.py \
  -k 'puts_answer_first or failed_turn_keeps_answer_first' -q
```

Expected: failures because the current report begins with `仿真与工具结果`, omits `仿真环境上下文`, and places the model conclusion later.

- [ ] **Step 3: Restore the approved section order using existing compact trajectory rendering**

Change `_render_narrative_turn` to assemble the stable structure before introducing richer trajectory semantics:

```python
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
    (
        f"- 总时长：{turn.duration_seconds:.2f} 秒"
        if turn.duration_seconds is not None
        else "- 总时长：未记录"
    ),
    f"- 原始回答：{_answer_link_or_label(turn, workspace, diagnostics)}",
    *_render_turn_evidence(context, turn, workspace, diagnostics),
    f"- 详细执行轨迹：{trace_link}",
]
```

Remove `_render_tool_results` from the main report path. Keep detailed trace-page JSON unchanged.

- [ ] **Step 4: Update the E2E section contract**

Replace the three current heading assertions with:

```python
assert report_text.count("### 回答") == len(prompts)
assert report_text.count("### 仿真环境上下文") == len(prompts)
assert report_text.count("### 智能体分析轨迹") == len(prompts)
for turn in context.turns:
    section = report_text.split(f"## {turn.ordinal}. ", maxsplit=1)[1]
    assert section.index("### 回答") < section.index("### 仿真环境上下文")
    assert section.index("### 仿真环境上下文") < section.index("### 智能体分析轨迹")
    assert section.index("### 智能体分析轨迹") < section.index("### 执行状态与证据")
```

Retain assertions that detailed trace pages exist and contain full input/output sections.

- [ ] **Step 5: Run report and continuous-analysis tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
```

Expected: all tests pass; main reports are answer-first and compact, while `trace.md` retains full structured detail.

- [ ] **Step 6: Commit the restored readable structure**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py
git commit -m "fix: restore readable analysis report structure"
```

---

### Task 2: Render capability-specific diagnostic trajectory milestones

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/report_trajectory.py`
- Create: `packages/grid-agent/tests/analysis/test_report_trajectory.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py:58-67,238-355,554-617`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`

**Interfaces:**
- Consumes: `TraceStep(sequence, turn_id, tool_call_id, capability, args, result, ok, duration_seconds)` built from Pi trace events.
- Produces: `render_analysis_trajectory(steps, *, decisions=(), reuse_notes=()) -> list[str]`, returning bounded Markdown without raw JSON fences.
- Produces: `TraceDecision(turn_id, tool_call_id, intent, decision, next_action)` for Task 3 decision attachment.

- [ ] **Step 1: Add pure trajectory projection tests for key inputs and results**

Create `test_report_trajectory.py` with a helper and representative capability families:

```python
from grid_agent.analysis.report_trajectory import TraceStep, render_analysis_trajectory


def step(
    capability: str,
    *,
    args: dict[str, object],
    result: dict[str, object],
    ok: bool = True,
    sequence: int = 1,
) -> TraceStep:
    return TraceStep(
        sequence=sequence,
        turn_id="analysis-test-t001",
        tool_call_id=f"call-{sequence}",
        capability=capability,
        args=args,
        result=result,
        ok=ok,
        duration_seconds=1.25,
    )


def test_trajectory_explains_work_inputs_and_diagnostic_results() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "topology.branch.endpoints.get",
                args={"branch_kind": "line", "branch_id": 11},
                result={"from_bus": 6, "to_bus": 11},
                sequence=1,
            ),
            step(
                "analysis.powerflow.ac.run",
                args={"operation": "powerflow.ac"},
                result={
                    "converged": True,
                    "total_active_loss": {"value": 43.6275, "unit": "MW"},
                },
                sequence=2,
            ),
            step(
                "model.dataset.query",
                args={
                    "dataset": "result.res_line",
                    "order_by": [{"field": "loading_percent", "direction": "desc"}],
                    "limit": 5,
                },
                result={
                    "rows": [{"line": 17, "loading_percent": 132.51}],
                    "row_count": 5,
                },
                sequence=3,
            ),
        )
    )
    text = "\n".join(lines)
    assert "核查线路 11 两端母线" in text
    assert "母线 6 → 母线 11" in text
    assert "交流潮流" in text and "收敛" in text and "43.6275 MW" in text
    assert "result.res_line" in text
    assert "loading_percent 降序" in text
    assert "前 5 项" in text
    assert "线路 17：132.51%" in text
    assert "```json" not in text
```

Add tests for contingency and violation families:

```python
def test_trajectory_preserves_contingency_and_violation_diagnostics() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.contingency.n_minus_one.run",
                args={"outage_kind": "single_branch", "branch_id": 17},
                result={
                    "status": "partial",
                    "scenario_count": 35,
                    "converged_scenarios": 34,
                    "worst_loading_percent": 132.51,
                },
                sequence=1,
            ),
            step(
                "analysis.result.violations.evaluate",
                args={"quantities": ["bus.vm_pu", "branch.loading_percent"]},
                result={
                    "status": "succeeded",
                    "summary": {
                        "constraint_source": "model",
                        "violation_count": 1,
                        "unavailable_quantities": [],
                    },
                },
                sequence=2,
            ),
        )
    )
    text = "\n".join(lines)
    assert "35 个场景" in text and "34 个收敛" in text
    assert "部分完成" in text and "132.51%" in text
    assert "模型约束" in text and "1 项越限" in text
```

- [ ] **Step 2: Add bounded fallback and redaction tests**

```python
def test_unknown_capability_uses_bounded_scalar_summary_and_redacts_internals() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.future.operation",
                args={
                    "subject": "line-17",
                    "mode": "screen",
                    "result_ref": "result:sha256:" + "1" * 64,
                    "access_token": "must-not-leak",
                },
                result={
                    "novel_metric": 12.75,
                    "unit": "kV",
                    "private_key": "must-not-leak",
                    "rows": list(range(100)),
                },
            ),
        )
    )
    text = "\n".join(lines)
    assert "analysis.future.operation" in text
    assert "subject=line-17" in text and "mode=screen" in text
    assert "novel_metric=12.75" in text and "unit=kV" in text
    assert "must-not-leak" not in text
    assert "result:sha256:" not in text
    assert len(text.splitlines()) <= 3
```

- [ ] **Step 3: Run the new unit suite and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report_trajectory.py -q
```

Expected: import failure because `report_trajectory.py` does not exist.

- [ ] **Step 4: Implement focused trajectory types and renderer**

Create the new module with stable pure interfaces:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


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


def render_analysis_trajectory(
    steps: Sequence[TraceStep],
    *,
    decisions: Sequence[TraceDecision] = (),
    reuse_notes: Sequence[str] = (),
) -> list[str]:
    if not steps and not reuse_notes:
        return ["未观察到与本题关联的领域工具调用。"]
    milestones = build_milestones(steps, decisions=decisions)
    lines = [f"- 复用：{note}" for note in reuse_notes]
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
```

Implement `build_milestones` and capability-family describers using recorded
values only. Use these semantic field priorities:

```python
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
```

Use exact capability branches for `context.open`, topology endpoints,
`analysis.powerflow.ac.run`, dataset query/rank, violation evaluation, and
N-1. The fallback emits at most four scalar key arguments and four scalar
result fields; nested collections become a count such as `rows=100 项`.

- [ ] **Step 5: Move `TraceStep` ownership and wire the pure renderer into the report**

Import the new types in `report.py`:

```python
from grid_agent.analysis.report_trajectory import (
    TraceDecision,
    TraceStep,
    render_analysis_trajectory,
)
```

Remove the local `_TraceStep`, `_render_trace_steps`, `_render_tool_results`,
and main-report JSON projection functions after all detailed-trace callers have
been updated to use `TraceStep`. Keep the detailed trace-page redaction helpers
that protect raw projections.

In `_render_narrative_turn`, use:

```python
*_render_analysis_trajectory_for_turn(context, turn, steps),
```

with this adapter:

```python
def _render_analysis_trajectory_for_turn(
    context: AnalysisContext,
    turn: TurnRecord,
    steps: Sequence[TraceStep],
) -> list[str]:
    return render_analysis_trajectory(
        steps,
        reuse_notes=_trajectory_reuse_notes(context, turn),
    )
```

- [ ] **Step 6: Run unit, report, and type checks**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py -q
uv run --project packages/grid-agent pyright \
  packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/src/grid_agent/analysis/report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_report_trajectory.py
```

Expected: all tests pass and Pyright reports `0 errors`.

- [ ] **Step 7: Commit semantic milestone rendering**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/src/grid_agent/analysis/report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_report_trajectory.py
git commit -m "feat: render diagnostic analysis trajectory milestones"
```

---

### Task 3: Attach decisions and lineage, then enforce trajectory density

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/report_trajectory.py`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`
- Modify: `packages/grid-agent/tests/analysis/test_report_trajectory.py`

**Interfaces:**
- Consumes: Task 2 `TraceStep`, `TraceDecision`, `TrajectoryMilestone`, and `render_analysis_trajectory(...)`.
- Produces: tolerant `_read_trace_decisions(path: Path) -> tuple[tuple[TraceDecision, ...], tuple[str, ...]]` and deterministic milestone compaction preserving important diagnostics.

- [ ] **Step 1: Add tests for setup grouping, retry distinction, and six-milestone density**

```python
def test_trajectory_groups_setup_and_equivalent_retries_without_hiding_failures() -> None:
    steps = (
        step("model.list", args={}, result={"models": [{"model": "ieee39"}]}, sequence=1),
        step(
            "context.open",
            args={"model": "ieee39"},
            result={"model": "ieee39", "counts": {"buses": 39, "lines": 35, "transformers": 11}},
            sequence=2,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["bad_field"]},
            result={"code": "unknown_field", "message": "bad_field is not published"},
            ok=False,
            sequence=3,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["loading_percent"], "limit": 5},
            result={"rows": [{"line": 17, "loading_percent": 132.51}], "row_count": 5},
            sequence=4,
        ),
    )
    text = "\n".join(render_analysis_trajectory(steps))
    assert text.count("准备 IEEE-39 仿真环境") == 1
    assert "2 次调用" in text
    assert "bad_field is not published" in text
    assert "改用 loading_percent" in text
    assert "线路 17：132.51%" in text
```

```python
def test_density_target_compacts_low_information_steps_but_keeps_important_ones() -> None:
    steps = tuple(
        step(
            "model.dataset.describe",
            args={"dataset": f"dataset-{index}"},
            result={"field_count": index + 1},
            sequence=index,
        )
        for index in range(1, 9)
    ) + (
        step(
            "analysis.powerflow.ac.run",
            args={"operation": "powerflow.ac"},
            result={"converged": False, "message": "Newton-Raphson did not converge"},
            ok=False,
            sequence=20,
        ),
    )
    lines = render_analysis_trajectory(steps)
    text = "\n".join(lines)
    assert sum(line[:1].isdigit() for line in lines) <= 6
    assert "其余 3 次数据集结构核对" in text
    assert "Newton-Raphson did not converge" in text
```

- [ ] **Step 2: Add tests for explicit decisions and cross-question reuse**

```python
def test_trajectory_attaches_recorded_decision_to_supporting_step() -> None:
    ranked = step(
        "result.branches.rank",
        args={"metric": "loading_percent", "limit": 5},
        result={"rows": [{"line": 17, "loading_percent": 132.51}]},
        sequence=4,
    )
    decision = TraceDecision(
        turn_id=ranked.turn_id,
        tool_call_id=ranked.tool_call_id,
        intent="识别过载线路",
        decision="线路 17 超过模型约束 100%",
        next_action="对线路 17 开展 N-1 校核",
    )
    text = "\n".join(render_analysis_trajectory((ranked,), decisions=(decision,)))
    assert "决策：线路 17 超过模型约束 100%；下一步：对线路 17 开展 N-1 校核" in text
```

```python
def test_trajectory_renders_reuse_without_repeating_original_calculation() -> None:
    lines = render_analysis_trajectory(
        (),
        reuse_notes=("第 5 题交流潮流结果，未重复计算",),
    )
    assert lines == ["- 复用：第 5 题交流潮流结果，未重复计算"]
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report_trajectory.py \
  -k 'groups_setup or density_target or attaches_recorded_decision or renders_reuse' -q
```

Expected: failures because Task 2 renders each call separately and the report does not yet parse native decision events.

- [ ] **Step 4: Implement deterministic compaction and recovery pairing**

Add these pure phases in `report_trajectory.py`:

```python
def build_milestones(
    steps: Sequence[TraceStep],
    *,
    decisions: Sequence[TraceDecision] = (),
) -> tuple[TrajectoryMilestone, ...]:
    narrated = tuple(_describe_step(item) for item in steps)
    with_setup = _group_adjacent_setup(narrated)
    with_retries = _group_equivalent_retries(with_setup)
    with_recovery = _annotate_recovery(with_retries)
    with_decisions = _attach_decisions(with_recovery, steps, decisions)
    return _compress_to_density_target(with_decisions, target=6)
```

`_compress_to_density_target` must retain every milestone where `important` is
true. Mark failures, partial/non-converged results, violations, rankings,
contingency results, calculations supporting the answer, and decision-bearing
milestones important. Compress only setup, describe/list, pagination, and
equivalent query milestones. If more than six important milestones remain,
return them all rather than dropping safety-relevant facts.

- [ ] **Step 5: Parse native decision events without making them mandatory**

Add a tolerant reader in `report.py`:

```python
def _read_trace_decisions(
    path: Path,
) -> tuple[tuple[TraceDecision, ...], tuple[str, ...]]:
    if not path.is_file():
        return (), ()
    decisions: list[TraceDecision] = []
    diagnostics: list[str] = []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return (), ("原生轨迹不可读，无法投影显式决策",)
    for line_number, line in enumerate(raw_lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            diagnostics.append(f"原生轨迹第 {line_number} 行格式错误")
            continue
        if not isinstance(event, Mapping) or event.get("event_type") != "business.decision.declared":
            continue
        scope = event.get("scope")
        payload = event.get("payload")
        if not isinstance(scope, Mapping) or not isinstance(payload, Mapping):
            diagnostics.append(f"原生轨迹第 {line_number} 行决策事件不完整")
            continue
        intent = payload.get("intent")
        decision = payload.get("decision")
        next_action = payload.get("next_action")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (intent, decision, next_action)
        ):
            diagnostics.append(f"原生轨迹第 {line_number} 行决策字段无效")
            continue
        assert isinstance(intent, str)
        assert isinstance(decision, str)
        assert isinstance(next_action, str)
        decisions.append(
            TraceDecision(
                turn_id=scope.get("turn_id") if isinstance(scope.get("turn_id"), str) else None,
                tool_call_id=(
                    scope.get("tool_call_id")
                    if isinstance(scope.get("tool_call_id"), str)
                    else None
                ),
                intent=intent,
                decision=decision,
                next_action=next_action,
            )
        )
    return tuple(decisions), tuple(diagnostics)
```

Read decisions once in `render_analysis_report`, append parse problems to
integrity diagnostics, filter them by turn/tool call, and pass them to
`render_analysis_trajectory`. An empty decision list is normal and must not add
a warning or fail the report.

- [ ] **Step 6: Derive compact reuse notes from authoritative context lineage**

Add:

```python
def _trajectory_reuse_notes(
    context: AnalysisContext,
    turn: TurnRecord,
) -> tuple[str, ...]:
    producer_ordinals = {item.turn_id: item.ordinal for item in context.turns}
    notes: list[str] = []
    for reference in turn.consumed_refs:
        calculation = context.domain_state.calculations.get(reference)
        if calculation is None or calculation.producer_turn_id == turn.turn_id:
            continue
        producer = producer_ordinals.get(calculation.producer_turn_id)
        label = _calculation_label(calculation.kind)
        notes.append(
            f"第 {producer} 题{label}结果，未重复计算"
            if producer is not None
            else f"前序{label}结果，未重复计算"
        )
    return tuple(dict.fromkeys(notes))
```

Do not infer reuse from prose or result IDs printed in the answer.

- [ ] **Step 7: Run the complete trajectory/report/analysis suites**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
uv run --project packages/grid-agent pyright \
  packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/src/grid_agent/analysis/report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_report_trajectory.py
```

Expected: all tests pass; Pyright reports `0 errors`; no decision tool is required for success.

- [ ] **Step 8: Commit decision, lineage, and density behavior**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/src/grid_agent/analysis/report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_report_trajectory.py
git commit -m "feat: compact analysis trajectory with lineage"
```

---

### Task 4: Synchronize current report contracts and run offline release gates

**Files:**
- Modify: `docs/architecture/analysis-context.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/DECISIONS.md`
- Verify and modify only if stale: `docs/RUNBOOK.md`
- Verify and modify only if stale: `docs/MANUAL-VALIDATION.md`

**Interfaces:**
- Consumes: final answer-first trajectory behavior from Tasks 1–3.
- Produces: current operational and architectural documentation plus complete offline verification evidence.

- [ ] **Step 1: Update the current architecture contract**

Replace the superseded report-order paragraph in
`docs/architecture/analysis-context.md` with this invariant:

```markdown
`report.md` is organized per instruction as **answer → simulation environment
context → observable agent analysis trajectory → execution status and
evidence**. The trajectory deterministically projects recorded tool intent,
semantic inputs, simulator results, lineage, failures, recovery, and optional
declared decisions into compact milestones. Complete inputs and outputs remain
in `turns/<ordinal>/trace.md`; the main report never expands raw result JSON or
invents private model reasoning.
```

Update only the structural reporting bullet in `CURRENT-STATE.md`. Do not add
session progress or next actions there.

- [ ] **Step 2: Append a superseding architecture decision**

Add a dated entry to `docs/status/DECISIONS.md`:

```markdown
## 2026-08-19 — Reports are answer-first with a bounded observable trajectory

- **Decision:** Each question renders answer, simulation context, compact
  observable agent trajectory, then execution status/evidence. Simulator
  results appear inside the step that produced them; raw JSON remains in the
  linked detailed trace.
- **Rationale:** A result-first JSON dump obscured answers, removed useful
  context, and weakened causal diagnosis. Generic capability labels were too
  repetitive to explain inputs, results, recovery, or reuse.
- **Boundary:** The renderer uses recorded actions, arguments, results, lineage,
  failures, and optional declared decisions. It does not expose or invent
  private chain-of-thought and does not require a model narration tool.
- **Density:** Target six milestones and 20–25 trajectory lines per question;
  failures and distinct safety-relevant findings are never dropped to meet the
  target.
- **Supersedes:** The report-order consequence in the 2026-08-19
  controller-owned submission decision; controller-owned submission itself is
  unchanged.
- **Specification:** `docs/superpowers/specs/2026-08-19-readable-agent-analysis-trajectory-report-design.md`
- **Plan:** `docs/superpowers/plans/2026-08-19-readable-agent-analysis-trajectory-report.md`
```

- [ ] **Step 3: Scan current docs and model contracts for stale claims**

Run:

```bash
rg -n "仿真与工具结果|模型结论.*执行状态|results before model prose|结果.*模型结论" \
  AGENTS.md README.md README.zh-CN.md configs/agent \
  skills/grid-static-analysis docs/RUNBOOK.md docs/MANUAL-VALIDATION.md \
  docs/architecture docs/status/CURRENT-STATE.md docs/status/DECISIONS.md
```

Expected: historical/superseded decision text may remain only when explicitly
labeled; no current instruction describes JSON-heavy result-first reports.

- [ ] **Step 4: Run focused static and behavior verification**

Run:

```bash
git diff --check
uv run --project packages/grid-agent pyright \
  packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/src/grid_agent/analysis/report_trajectory.py \
  packages/grid-agent/tests/analysis/test_report.py \
  packages/grid-agent/tests/analysis/test_report_trajectory.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
```

Expected: no whitespace/type errors and all focused tests pass.

- [ ] **Step 5: Run all offline release gates**

Run in order:

```bash
make doctor
make test
make test-e2e
make validate
```

Expected: every command exits `0`; the capability matrix remains `24/24
(100.00%)` and release-ready. Do not run `make validate-provider`.

- [ ] **Step 6: Commit documentation**

Stage only files actually changed for this task:

```bash
git add docs/architecture/analysis-context.md \
  docs/status/CURRENT-STATE.md docs/status/DECISIONS.md
git diff --cached --check
git commit -m "docs: document readable analysis trajectories"
```

If `RUNBOOK.md` or `MANUAL-VALIDATION.md` required a current-contract correction,
include only the necessary files in the same documentation commit.

- [ ] **Step 7: Verify main-worktree closure**

Run:

```bash
git branch --show-current
git worktree list
git status --short
git log --oneline -10
```

Expected: branch is `main`; there is no task-created worktree or temporary
branch; only the user's pre-existing status-document changes and untracked
artifacts remain. Do not push, move `v1.0.0`, or create a new tag without a
separate request.

---

## Final Acceptance Checklist

- [ ] Every question begins with the accepted answer or the explicit missing-answer placeholder.
- [ ] `仿真环境上下文` is restored and contains model, constraints, calculations, scenarios, and reuse when available.
- [ ] `智能体分析轨迹` is the explanatory backbone; key simulator results are embedded in their producing steps.
- [ ] Main-report trajectory steps include diagnostic work descriptions, semantic inputs, results, status, and duration without raw JSON blocks.
- [ ] Repeated calls are distinguishable by parameters/results; equivalent setup/retries are compacted.
- [ ] Real decision events attach to their supporting steps; no decision tool is required.
- [ ] Cross-question result reuse is derived from authoritative lineage and rendered once.
- [ ] Six-milestone/20–25-line density target is enforced without hiding failures or distinct safety-relevant findings.
- [ ] Failed turns retain successful prior steps, concrete failure reasons, and recovery actions.
- [ ] Unknown capabilities use a bounded redacted fallback.
- [ ] Detailed `trace.md`, raw tool-result artifacts, and evidence links remain complete and reachable.
- [ ] Controller-owned answer submission, current-run evidence validation, stdout envelope, and stderr diagnostics are unchanged.
- [ ] Pyright, focused suites, `make doctor`, `make test`, `make test-e2e`, and `make validate` pass without a billed provider call.
- [ ] Work ends on `main` without a temporary worktree or branch.
