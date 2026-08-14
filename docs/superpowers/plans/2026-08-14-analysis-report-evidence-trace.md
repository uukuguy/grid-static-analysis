# Analysis 报告证据与轨迹 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每题报告中展示按引用归属的证据，并提供可读、可追溯的详细执行轨迹页。

**Architecture:** `TurnRecord.produced_refs` 和 `consumed_refs` 是题目与证据的权威关联；报告从这些引用解析 `EvidenceRecord`，而不依赖全局 `EvidenceRecord.turn_id`。`report.py` 从现有 trace 和 tool-result 工件生成 `turns/<ordinal>/trace.md`，正文只链接该页。

**Tech Stack:** Python 3.14、Pydantic、pytest、Markdown、现有 `AnalysisWorkspace`。

## Global Constraints

- 不改写已提交的 `answer_output`，也不让报告投影失败阻止分析结果。
- 只读 `runs/<analysis_id>/` 既有工件；所有链接使用 workspace 内相对路径。
- 轨迹只记录工具调用输入、输出、状态与耗时；不得导出模型隐含推理。
- 输入和输出摘要必须移除内容寻址内部引用；原始 JSON 由链接保留。
- 缺失或畸形工件只能产生局部提示，不能中断报告。

---

### Task 1: 按题目引用展示证据

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py:186-207`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`

**Interfaces:**
- Consumes: `TurnRecord.produced_refs`, `TurnRecord.consumed_refs`, `AnalysisContext.evidence`。
- Produces: `_render_turn_evidence(...) -> list[str]`，每项带生成/复用标签和证据链接。

- [ ] **Step 1: Write the failing tests**

```python
def test_report_shows_evidence_referenced_by_turn_even_when_evidence_turn_id_is_global(...):
    report = render_analysis_report(...)
    section = report.split("### 证据来源", 1)[1].split("## 2.", 1)[0]
    assert "网络拓扑事实" in section
    assert "本题生成" in section
    assert "evidence/network-facts/" in section

def test_report_marks_reused_evidence(...):
    report = render_analysis_report(...)
    assert "复用前序分析" in report
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py -q`

Expected: FAIL because `_render_turn_evidence` filters only `record.turn_id == turn.turn_id`.

- [ ] **Step 3: Implement minimal reference-based rendering**

```python
def _evidence_for_turn(context: AnalysisContext, turn: TurnRecord) -> list[tuple[EvidenceRecord, str]]:
    produced = set(turn.produced_refs)
    consumed = set(turn.consumed_refs)
    return [
        (record, "本题生成" if record.evidence_ref in produced else "复用前序分析")
        for record in context.evidence.values()
        if record.evidence_ref in produced | consumed
    ]
```

Use `_workspace_link` with `record.path`; derive a short description from `record.summary["evidence_type"]` and `record.summary["capability_id"]`. If no record matches, write `本题没有可追溯的仿真证据。` rather than claiming a reuse that cannot be located.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py packages/grid-agent/tests/analysis/test_report.py
git commit -m "fix: show evidence by turn references"
```

### Task 2: 生成每题详细执行轨迹页

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py:32-291`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`
- Modify: `docs/architecture/analysis-context.md:124-132`

**Interfaces:**
- Consumes: `_TraceStep`, `AnalysisWorkspace.turn_path(ordinal)`, `workspace.tool_results_path`。
- Produces: `_write_turn_trace_pages(...) -> dict[str, str]` and `turns/<ordinal>/trace.md`.

- [ ] **Step 1: Write the failing tests**

```python
def test_report_writes_per_turn_detailed_trace_with_raw_artifact_links(...):
    render_analysis_report(...)
    detail_path = workspace.turn_path(1) / "trace.md"
    detail = detail_path.read_text(encoding="utf-8")
    assert "## 1. 按支路运行指标筛选和排序" in detail
    assert "### 输入" in detail and "loading_percent" in detail
    assert "### 输出摘要" in detail
    assert "tool-results/" in detail

def test_report_links_detailed_trace_from_main_report(...):
    report = render_analysis_report(...)
    assert "详细执行轨迹" in report
    assert "turns/001/trace.md" in report
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py -q`

Expected: FAIL because no `turns/<ordinal>/trace.md` is generated or linked.

- [ ] **Step 3: Implement trace-page projection**

```python
def _write_turn_trace_pages(... ) -> dict[str, str]:
    paths = {}
    for turn in context.turns:
        path = workspace.turn_path(turn.ordinal) / "trace.md"
        _write_text_atomic(path, _render_turn_trace_page(turn, _steps_for_turn(...), workspace, diagnostics))
        paths[turn.turn_id] = str(path.relative_to(workspace.root_path))
    return paths
```

For each `_TraceStep`, render a numbered section with capability, `ok` status, duration, a fenced JSON input after `_redact_internal_refs`, and a compact result summary. Link `tool-results/<turn_id>/<tool_call_id>.json` only after `_normalize_workspace_relative_path` accepts it. When the artifact is absent, state `原始工具结果工件不可用` and retain the trace summary.

Add `- 详细执行轨迹：[查看本题调用输入、输出和原始工件](turns/<ordinal>/trace.md)` below the main-report process summary.

- [ ] **Step 4: Run focused tests and static checks**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q && uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/analysis/report.py`

Expected: all tests pass; `0 errors, 0 warnings`.

- [ ] **Step 5: Update report contract and commit**

Document the main-report/detail-page split in `docs/architecture/analysis-context.md`.

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py packages/grid-agent/tests/analysis/test_report.py packages/grid-agent/tests/e2e/test_continuous_analysis.py docs/architecture/analysis-context.md
git commit -m "feat: add detailed analysis trace pages"
```

### Task 3: Verify the full analysis contract

**Files:**
- Verify only: source and tests from Tasks 1–2.

**Interfaces:**
- Consumes: complete report projection.
- Produces: verification evidence; no source interface changes.

- [ ] **Step 1: Run full gates**

Run: `make test && make test-e2e && make validate`

Expected: all pytest suites pass; offline validation reports 9/9 and scripted-Pi validation reports 10/10.

- [ ] **Step 2: Check generated artifacts**

Run: `find runs -path '*/turns/*/trace.md' -print | tail -10`

Expected: each exercised analysis turn has a trace page; each is linked from its report section.

- [ ] **Step 3: Commit verification-only documentation if needed**

Do not commit ignored `runs/` outputs or unrelated user changes. If no tracked verification document changed, do not create an empty commit.

## Self-Review

- Spec coverage: Task 1 covers reference-based evidence, including reuse; Task 2 covers detailed trace pages, raw artifact links and safe degradation; Task 3 covers regression verification.
- Placeholder scan: no TBD/TODO or unspecified handling remains.
- Type consistency: Tasks use existing `AnalysisContext`, `TurnRecord`, `_TraceStep`, `AnalysisWorkspace`, and `_write_text_atomic` interfaces.
