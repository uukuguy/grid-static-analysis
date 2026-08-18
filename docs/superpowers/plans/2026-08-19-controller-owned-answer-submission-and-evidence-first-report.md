# Controller-Owned Answer Submission and Evidence-First Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the controller commit ordinary model final text, remove model-visible `grid_submit_answer`, fail continuous analysis on any failed required turn, and render recorded tool results as the report's factual body.

**Architecture:** Pi remains responsible for model conversation and bounded grid-tool calls, while Python controllers own answer persistence and terminal state. Continuous-analysis submissions derive answer-level lineage from the active turn's projected references. Reports are deterministic projections of recorded tool results followed by model prose and integrity diagnostics; they contain no semantic evaluator.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest 9, Node.js 22, native Pi RPC JSONL, Markdown report rendering, `grid-capability` protocol 1.0, pandapower 3.4.0.

## Global Constraints

- `grid-agent` writes exactly one JSON object to stdout with `question_id` and `answer_output`; diagnostics go to stderr.
- Numerical or network-specific claims cross the simulator boundary only through `gridctl` and `grid-capability` protocol version `1.0`.
- The simulator remains pinned to pandapower `3.4.0`.
- Pi receives only project-defined grid tools and `grid_guide_open`; it receives no shell, generic filesystem, arbitrary Python, raw pandapower, legacy query alias, or answer-persistence tool.
- Successful tool results already captured in a failed turn remain available in its partial report.
- No billed `make validate-provider` run is part of this plan.
- Do not move the existing release tag or delete/migrate existing user run data.
- Preserve unrelated working-tree changes and commit only files owned by each task.

---

## Planned file structure

- `packages/grid-agent/src/grid_agent/analysis/turns.py` — owns controller-side answer draft construction, lineage collection, validation, and answer artifact commit.
- `packages/grid-agent/src/grid_agent/analysis/runner.py` — owns per-turn final-text consumption and fail-closed batch state.
- `packages/grid-agent/src/grid_agent/analysis/report.py` — owns evidence-first deterministic Markdown projection.
- `packages/grid-agent/src/grid_agent/cli/app.py` — publishes Pi final text for single-question online runs and removes model-draft loaders.
- `packages/grid-agent/src/grid_agent/runtime/environment.py` — removes the answer-draft path from the model process environment.
- `packages/pi-grid-tools/src/domain-tools.mjs` — registers analysis/guide/context/decision tools only; no answer-persistence tool.
- `packages/grid-agent/tests/analysis/test_turns.py` — controller submission and lineage unit coverage.
- `packages/grid-agent/tests/analysis/test_runner.py` — turn/batch terminal semantics and prompt coverage.
- `packages/grid-agent/tests/analysis/test_report.py` — trace-to-main-report semantic parity coverage.
- `packages/grid-agent/tests/cli/test_app.py` — CLI analysis envelope coverage after obsolete draft verification helpers are removed.
- `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py` — scripted online `run` final-text acceptance and empty-response failure.
- `packages/grid-agent/tests/e2e/test_semantic_pi_path.py` — direct final-text semantic tool path.
- `packages/grid-agent/tests/e2e/test_continuous_analysis.py` — multi-turn controller submission and report coverage.
- `packages/grid-agent/tests/runtime/test_pi_config.py` and `test_provider_adapters.py` — runtime environment contract without `GRID_AGENT_ANSWER_DRAFT`.
- `packages/pi-grid-tools/test/package.test.mjs` and `test/domain-tools.test.mjs` — exact model-visible tool surface.
- `AGENTS.md`, `configs/agent/system-policy.md`, `skills/grid-static-analysis/**`, `docs/RUNBOOK.md`, `docs/MANUAL-VALIDATION.md`, and current architecture docs — operational documentation for controller-owned submission.

---

### Task 1: Add controller-owned continuous-turn submission

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/turns.py`
- Modify: `packages/grid-agent/tests/analysis/test_turns.py`

**Interfaces:**
- Consumes: `AnalysisContextStore.snapshot.current_turn`, whose `consumed_refs` and `produced_refs` contain projected current-run lineage.
- Produces: `TurnController.submit(handle: ActiveTurnHandle, *, answer_output: str, duration_seconds: float) -> FinalizedTurn`.
- Preserves temporarily: `TurnController.finalize(...)` so the rest of the tree stays green until Tasks 2 and 3 migrate every caller.

- [ ] **Step 1: Write failing controller-submission tests**

Add tests that establish three exact behaviors:

```python
def test_controller_submits_model_text_with_projected_turn_refs(tmp_path: Path) -> None:
    controller, recorder, store, workspace, handle, result_ref, evidence_ref = answer_fixture(tmp_path)
    register_answer_lineage(store, handle, result_ref, evidence_ref)

    completed = controller.submit(
        handle,
        answer_output="线路结果来自本题仿真。",
        duration_seconds=1.0,
    )

    draft = json.loads(
        (workspace.turn_path(1) / "answer-draft.json").read_text(encoding="utf-8")
    )
    assert completed.status == "success"
    assert completed.answer_output == "线路结果来自本题仿真。"
    assert draft["turn_id"] == handle.turn_id
    assert draft["turn_nonce"] == handle.turn_nonce
    assert draft["result_refs"] == [result_ref]
    assert draft["claim_evidence_refs"] == [evidence_ref]
    assert draft["claims"] == []
    events = RunEventReader(recorder.events_path).read_prefix().events
    assert not any(event.event_type == "business.claim.declared" for event in events)


def test_controller_submission_keeps_only_result_and_evidence_refs() -> None:
    refs = turns_module._answer_level_refs(
        (
            "context:sha256:" + "1" * 64,
            "result:sha256:" + "2" * 64,
            "evidence:sha256:" + "3" * 64,
            "result:sha256:" + "2" * 64,
            "observation:sha256:" + "4" * 64,
        )
    )
    assert refs == (
        ("result:sha256:" + "2" * 64,),
        ("evidence:sha256:" + "3" * 64,),
    )


def test_controller_rejects_empty_model_final_text(harness: Harness) -> None:
    turn = harness.turns.start(1, "没有最终文本")

    finalized = harness.turns.submit(
        turn,
        answer_output="  \n",
        duration_seconds=0.5,
    )

    assert finalized.status == "failed"
    assert finalized.error == "model returned no final answer"
    assert harness.store.snapshot.turns[-1].status == "failed"
    assert not (harness.workspace.turn_path(1) / "answer.json").exists()
```

Implement `register_answer_lineage` with normal `result.registered` and
`evidence.registered` context events; do not mutate frozen Pydantic state in the
actual test. Keep `_answer_level_refs` as a private pure helper and test it
directly with a tuple of reference strings.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_turns.py \
  -k 'controller_submits_model_text or submission_keeps_only or rejects_empty_model' -q
```

Expected: failure because `TurnController.submit` and `_answer_level_refs` do
not exist.

- [ ] **Step 3: Extract accepted-draft commit logic and implement `submit`**

Refactor the existing successful half of `finalize` into a private method, then
add the new entry point:

```python
def submit(
    self,
    handle: ActiveTurnHandle,
    *,
    answer_output: str,
    duration_seconds: float,
) -> FinalizedTurn:
    if not answer_output.strip():
        return self.fail(
            handle,
            error="model returned no final answer",
            duration_seconds=duration_seconds,
        )
    active = self._store.snapshot.current_turn
    if active is None or active.turn_id != handle.turn_id:
        raise StaleAnswerDraftError("answer submission is bound to a different turn")
    result_refs, evidence_refs = _answer_level_refs(
        (*active.consumed_refs, *active.produced_refs)
    )
    draft = {
        "turn_id": handle.turn_id,
        "turn_nonce": handle.turn_nonce,
        "submission_id": handle.turn_id,
        "answer_output": answer_output,
        "result_refs": list(result_refs),
        "claim_evidence_refs": list(evidence_refs),
        "claims": [],
        "submission_diagnostics": [],
    }
    raw_draft = _json_bytes(draft)
    _write_bytes_atomic(self._workspace.active_answer_draft_path, raw_draft)
    return self._accept_draft(
        handle,
        draft=draft,
        raw_draft=raw_draft,
        duration_seconds=duration_seconds,
    )


def _answer_level_refs(
    references: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    unique = tuple(dict.fromkeys(references))
    return (
        tuple(ref for ref in unique if ref.startswith("result:sha256:")),
        tuple(ref for ref in unique if ref.startswith("evidence:sha256:")),
    )


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
```

`_accept_draft` must retain the existing ordering: validate references, archive
the draft, write audit and answer files, append `answer.submitted`, record any
diagnostics, append successful `turn.completed`, and only then remove the
active-turn file.

- [ ] **Step 4: Run controller tests and confirm GREEN**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_turns.py -q
```

Expected: all `test_turns.py` tests pass, including the temporary legacy-draft
coverage.

- [ ] **Step 5: Commit the controller API**

```bash
git add packages/grid-agent/src/grid_agent/analysis/turns.py \
  packages/grid-agent/tests/analysis/test_turns.py
git commit -m "feat: let controller submit analysis answers"
```

---

### Task 2: Consume final text and fail continuous analysis correctly

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/runner.py`
- Modify: `packages/grid-agent/tests/analysis/test_runner.py`
- Modify: `packages/grid-agent/tests/e2e/test_continuous_analysis.py`

**Interfaces:**
- Consumes: `TurnController.submit(...)` from Task 1 and `PiSession.prompt_and_wait(...) -> str`.
- Produces: stop-on-first-failed-turn semantics and a completion precondition requiring every turn to be successful with an answer path.

- [ ] **Step 1: Replace the permissive runner test with fail-closed expectations**

Change the missing-answer regression to assert that the second instruction is
never sent and no completed terminal event exists:

```python
def test_runner_stops_and_fails_when_model_returns_no_final_answer(
    runner_harness: RunnerHarness,
) -> None:
    runner_harness.pi.behavior = [NO_DRAFT_AGENT_END, SHOULD_NOT_RUN]

    outcome = runner_harness.runner.run(
        AnalysisRequest(analysis_id="analysis-test", instructions=("一", "二"))
    )

    event_types = [
        json.loads(line)["event_type"]
        for line in runner_harness.workspace.context_events_path.read_text().splitlines()
    ]
    assert outcome.status == "failed"
    assert len(runner_harness.pi.prompts) == 1
    assert runner_harness.store.snapshot.turns[0].status == "failed"
    assert runner_harness.store.snapshot.status == "failed"
    assert "analysis.failed" in event_types
    assert "analysis.completed" not in event_types
```

Update `FakePi.prompt_and_wait` so normal behaviors return `action["answer"]`
without writing `active_answer_draft_path`. Add assertions that the prompt no
longer names `grid_submit_answer` and still prohibits internal reference IDs in
reader-facing text.

- [ ] **Step 2: Run the runner regression and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_runner.py \
  -k 'stops_and_fails_when_model_returns_no_final_answer or records_submitted_answer' -q
```

Expected: the current runner continues after the failed turn or depends on the
model-written draft.

- [ ] **Step 3: Submit returned text and terminate on failed finalization**

Change the turn loop to retain the RPC return value:

```python
answer_output = self._pi.prompt_and_wait(
    self._prompt_for(instruction),
    on_event=self._progress_callback,
    on_semantic_event=lambda event, sequence, turn_id=handle.turn_id: self._observe_semantic_event(
        event,
        turn_id=turn_id,
        trace_sequence=sequence,
    ),
    require_answer_text=True,
    capture=self._capture,
)
finalized = self._turns.submit(
    handle,
    answer_output=answer_output,
    duration_seconds=max(0.0, time.monotonic() - handle.started_monotonic),
)
self._end_capture()
if finalized.status != "success":
    error = finalized.error or "turn did not produce an accepted answer"
    self._checkpoint_after_turn(finalized)
    self._fail_analysis(error, total_turns=len(request.instructions))
    return self._outcome(request, "failed", error)
```

Before appending `analysis.completed`, enforce the terminal invariant:

```python
def _require_all_turns_succeeded(self, *, total_turns: int) -> None:
    turns = self._store.snapshot.turns
    if len(turns) != total_turns:
        raise ContextStoreError("analysis cannot complete before every instruction terminates")
    if any(turn.status != "success" or not turn.answer_path for turn in turns):
        raise ContextStoreError("analysis cannot complete with a failed or unanswered turn")
```

Call this method immediately before `_verify_running_state_before_completion`.
Rewrite `_prompt_for` so it ends with a direct final-text requirement:

```python
"完成分析工具调用后，直接返回面向报告读者的最终回答。"
"最终回答不得包含 context/result/evidence/asset/constraint 等内部引用 ID。"
```

Remove the old sentence requiring `grid_submit_answer`.

- [ ] **Step 4: Update scripted continuous-analysis fixtures**

In `test_continuous_analysis.py`, make each scripted Pi response emit its
actual expected answer as `text_delta`/assistant text. Remove helper code that
writes `GRID_AGENT_ANSWER_DRAFT` and remove assertions that
`grid_submit_answer` appears in the model tool trace. Preserve assertions for
`answer.submitted`, current-run evidence, tool ordering, and the stdout
envelope.

- [ ] **Step 5: Run focused runner and continuous E2E tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
```

Expected: all tests pass; a failed required turn yields `analysis.failed` and
never `analysis.completed`.

- [ ] **Step 6: Commit continuous-analysis state semantics**

```bash
git add packages/grid-agent/src/grid_agent/analysis/runner.py \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py
git commit -m "fix: fail analysis without accepted model text"
```

---

### Task 3: Remove model-owned submission from online runtime

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/turns.py`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/grid-agent/tests/cli/test_app.py`
- Modify: `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py`
- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`
- Modify: `packages/grid-agent/tests/runtime/test_pi_config.py`
- Modify: `packages/grid-agent/tests/runtime/test_provider_adapters.py`
- Modify: `packages/pi-grid-tools/test/package.test.mjs`
- Modify: `packages/pi-grid-tools/test/domain-tools.test.mjs`

**Interfaces:**
- Consumes: direct final-text runner behavior from Task 2.
- Produces: model-visible tool registration without `grid_submit_answer`, online `run` publication from RPC text, and no `GRID_AGENT_ANSWER_DRAFT` process capability.

- [ ] **Step 1: Write model-surface and online-response regressions**

Change the Node surface assertions to require absence:

```javascript
assert.equal(
  registered.some((tool) => tool.name === "grid_submit_answer"),
  false,
);
assert.deepEqual(
  registered.map((tool) => tool.name).sort(),
  [
    "grid_environment_describe",
    "grid_guide_open",
    "grid_topology_branch_endpoints",
  ],
);
```

Replace the old online draft requirement with these E2E expectations:

```python
def test_online_path_uses_model_final_text_without_answer_tool(tmp_path: Path) -> None:
    # Scripted Pi acknowledges, emits "free-form answer", and ends.
    completed = run_scripted_pi(tmp_path, final_text="free-form answer")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["answer_output"] == "free-form answer"


def test_online_path_rejects_empty_model_final_text(tmp_path: Path) -> None:
    completed = run_scripted_pi(tmp_path, final_text=None)
    assert completed.returncode == 1
    assert "Pi agent ended without answer text" in completed.stderr
```

Add a runtime assertion:

```python
assert "GRID_AGENT_ANSWER_DRAFT" not in launch.environment
```

- [ ] **Step 2: Run the cross-language regressions and confirm RED**

Run:

```bash
npm test --prefix packages/pi-grid-tools
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py \
  packages/grid-agent/tests/runtime/test_pi_config.py -q
```

Expected: Node still registers `grid_submit_answer`, the online CLI still
loads a draft, and runtime configuration still exports the draft path.

- [ ] **Step 3: Publish ordinary RPC text in the online CLI**

Replace the online `run` submission block with:

```python
answer = rpc.prompt_and_wait(
    request.question,
    on_event=on_pi_event,
    on_heartbeat=progress.heartbeat,
    require_answer_text=True,
)
```

Delete `SubmittedAnswer`, `_load_verified_answer_draft`,
`_load_submitted_answer`, and the private single-run evidence/draft validation
helpers used only by those loaders. Delete their unit tests from
`test_app.py`; simulator artifact integrity remains covered by the analysis
projector, trajectory verifier, and simulator tests.

- [ ] **Step 4: Remove the submission tool and draft environment**

In `domain-tools.mjs`, remove the `createSubmitAnswerTool` registration and
delete its implementation plus its reference-normalization-only helpers.
Retain `referenceKind` only if `grid_record_decision` still calls it; otherwise
delete it too.

Remove `answer_draft_path` from `RuntimePaths` and remove this line from
`build_pi_environment`:

```python
allowed["GRID_AGENT_ANSWER_DRAFT"] = str(paths.answer_draft_path)
```

Remove the `answer_draft_path=` argument from every `RuntimePaths(...)`
construction and fixture. Keep `AnalysisWorkspace.active_answer_draft_path` as
the controller-private staging path.

- [ ] **Step 5: Remove the temporary legacy TurnController entry point**

Delete `TurnController.finalize` and draft parsing branches that accept
model-written files. Keep controller-private draft archival and historical
report reading. Update `test_turns.py` to use `submit` everywhere and remove
stale/malformed model-draft tests that no longer describe a reachable runtime
boundary.

- [ ] **Step 6: Update semantic scripted-Pi fixtures**

In `test_semantic_pi_path.py`, emit the expected final answer as assistant text
after the last grid-tool result. Remove the scripted `grid_submit_answer` start,
end, and filesystem write. Assert that the trace contains simulator tool calls
and excludes `grid_submit_answer`.

- [ ] **Step 7: Run all affected Python and Node tests**

Run:

```bash
npm run check --prefix packages/pi-grid-tools
npm test --prefix packages/pi-grid-tools
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_turns.py \
  packages/grid-agent/tests/cli/test_app.py \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/runtime/test_provider_adapters.py \
  packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q
```

Expected: all tests pass, and no model-visible or process-environment answer
submission capability remains.

- [ ] **Step 8: Commit the runtime boundary change**

```bash
git add packages/grid-agent/src/grid_agent/cli/app.py \
  packages/grid-agent/src/grid_agent/runtime/environment.py \
  packages/grid-agent/src/grid_agent/analysis/turns.py \
  packages/pi-grid-tools/src/domain-tools.mjs \
  packages/grid-agent/tests/cli/test_app.py \
  packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/runtime/test_provider_adapters.py \
  packages/pi-grid-tools/test/package.test.mjs \
  packages/pi-grid-tools/test/domain-tools.test.mjs
git commit -m "refactor: make answer submission controller owned"
```

---

### Task 4: Render tool results as the report's factual body

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`

**Interfaces:**
- Consumes: `_TraceStep` records produced by `_read_trace_steps`.
- Produces: `_render_tool_results(steps: Sequence[_TraceStep]) -> list[str]` and `_reader_result_value(value: Any, *, depth: int = 0) -> Any`.

- [ ] **Step 1: Add semantic-parity report tests**

Extend the fixture trace with endpoint, power-flow, ranking, dataset-query, and
contingency results containing distinctive values. Assert section order and
value preservation:

```python
def test_report_renders_recorded_tool_results_before_model_conclusion(
    report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    first_turn = report.split("## 2.", maxsplit=1)[0]
    assert first_turn.index("### 仿真与工具结果") < first_turn.index("### 模型结论")
    assert '"from_bus": 6' in first_turn
    assert '"to_bus": 11' in first_turn
    assert '"value": 43.6275' in first_turn
    assert '"loading_percent": 132.51' in first_turn
    assert '"scenario_count": 35' in first_turn


def test_failed_turn_keeps_successful_tool_result_in_main_report(
    failed_report_fixture: ReportFixture,
) -> None:
    report = render_analysis_report(
        context=failed_report_fixture.context,
        workspace=failed_report_fixture.workspace,
        environment={},
    )
    failed_turn = report.split("## 2. 失败回合", maxsplit=1)[1]
    assert "状态：未完成" in failed_turn
    assert '"from_bus": 6' in failed_turn
    assert "模型未返回可接受的最终回答" in failed_turn


def test_unknown_capability_uses_structured_result_fallback(
    report_fixture: ReportFixture,
) -> None:
    report = render_report_with_tool_result(
        report_fixture,
        capability="analysis.future.operation",
        result={"novel_metric": 12.75, "unit": "kV"},
    )
    assert "analysis.future.operation" in report
    assert '"novel_metric": 12.75' in report
    assert '"unit": "kV"' in report


def test_report_keeps_historical_submit_events_readable(
    report_fixture: ReportFixture,
) -> None:
    report = render_report_with_tool_result(
        report_fixture,
        capability="grid_submit_answer",
        result={"ok": True},
    )
    assert "grid_submit_answer" in report
    assert '"ok": true' in report
```

Also assert that internal hashes and secret-shaped keys are absent from the
reader-facing body while the detailed trace link remains present.

- [ ] **Step 2: Run report tests and confirm RED**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report.py \
  -k 'recorded_tool_results or failed_turn_keeps or unknown_capability' -q
```

Expected: failures because the main report currently emits generic labels and
places the model answer first.

- [ ] **Step 3: Implement deterministic bounded result projection**

Add a recursive reader projection that removes internal references and
credential-shaped fields while retaining result values:

```python
_READER_MAX_DEPTH = 6
_READER_MAX_MAPPING_ITEMS = 50
_READER_MAX_SEQUENCE_ITEMS = 20


def _reader_result_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= _READER_MAX_DEPTH:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        visible = [
            (str(key), item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_internal_or_secret_field(str(key))
        ]
        for key, item in visible[:_READER_MAX_MAPPING_ITEMS]:
            items[key] = _reader_result_value(item, depth=depth + 1)
        if len(visible) > _READER_MAX_MAPPING_ITEMS:
            items["_omitted_fields"] = len(visible) - _READER_MAX_MAPPING_ITEMS
        return items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = [
            _reader_result_value(item, depth=depth + 1)
            for item in value[:_READER_MAX_SEQUENCE_ITEMS]
        ]
        if len(value) > _READER_MAX_SEQUENCE_ITEMS:
            items.append({"_omitted_items": len(value) - _READER_MAX_SEQUENCE_ITEMS})
        return items
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _is_internal_or_secret_field(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered.endswith("_ref")
        or lowered.endswith("_refs")
        or any(term in lowered for term in ("secret", "token", "authorization", "api_key"))
    )
```

The complete raw result remains linked through the existing per-turn trace and
tool-result artifact.

- [ ] **Step 4: Put tool results before model prose**

Replace `_render_narrative_turn` section order with:

```python
lines = [
    "",
    f"## {turn.ordinal}. {_md(turn.instruction)}",
    "",
    "### 仿真与工具结果",
    "",
    *_render_tool_results(steps),
    "",
    "### 模型结论",
    "",
    answer if turn.answer_path else "模型未返回可接受的最终回答。",
    "",
    "### 执行状态与证据",
    "",
    f"- 状态：{_reader_status(turn.status)}",
    f"- 总时长：{turn.duration_seconds:.2f} 秒" if turn.duration_seconds is not None else "- 总时长：未记录",
    f"- 原始回答：{_answer_link_or_label(turn, workspace, diagnostics)}",
    *_render_turn_evidence(context, turn, workspace, diagnostics),
    f"- 详细执行轨迹：{trace_link}",
]
```

Implement `_render_tool_results` so every `_TraceStep` gets its capability,
status, duration, existing compact summary, and a fenced JSON projection of
`step.result`. A tool with `{}` output still gets an explicit `结果为空` line.

Rename the batch `## 审计复核` section to `## 完整性诊断`. Keep only unresolved
limitations, report-generation diagnostics, and forensic links. Do not call an
evaluator or compare answer prose against an expected answer.

- [ ] **Step 5: Run the full report suite**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_report.py -q
```

Expected: all report tests pass; reader-facing main sections contain recorded
tool values and failed turns retain their successful tool output.

- [ ] **Step 6: Commit the evidence-first report**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py \
  packages/grid-agent/tests/analysis/test_report.py
git commit -m "fix: make tool results authoritative in analysis reports"
```

---

### Task 5: Synchronize operational contracts and run release gates

**Files:**
- Modify: `AGENTS.md` (`CLAUDE.md` follows through the existing symlink)
- Modify: `configs/agent/system-policy.md`
- Modify: `skills/grid-static-analysis/SKILL.md`
- Modify: `skills/grid-static-analysis/references/ac-powerflow.md`
- Modify: `skills/grid-static-analysis/references/result-query.md`
- Modify: `skills/grid-static-analysis/references/contingency-analysis.md`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/MANUAL-VALIDATION.md`
- Modify: `docs/architecture/analysis-context.md`
- Modify: `docs/architecture/pandapower-capability-composition.md`
- Modify: `docs/status/DECISIONS.md`
- Modify if structurally stale after implementation: `docs/status/CURRENT-STATE.md`

**Interfaces:**
- Consumes: final code and verified behavior from Tasks 1-4.
- Produces: current operational guidance that distinguishes model analysis from controller answer commit.

- [ ] **Step 1: Update current agent and runtime contracts**

Use this invariant consistently:

```markdown
Pi/LLM may use only project-defined grid tools and `grid_guide_open`.
The model returns reader-facing final text; `grid-agent` binds current-turn
result/evidence references and commits the answer deterministically.
```

In `system-policy.md`, replace submission-tool instructions with:

```markdown
- After completing the required grid-tool calls, return the final user-facing
  answer as ordinary assistant text.
- Do not include internal result, evidence, context, asset, constraint, path,
  or nonce identifiers in that text; the runtime binds current-turn lineage.
```

- [ ] **Step 2: Update Skill and operator documentation**

Change AC, ranking, and contingency guidance from “submit these references via
`grid_submit_answer`” to “use the returned current-run results; the controller
binds the turn's consumed and produced result/evidence references.”

Update RUNBOOK and manual-validation expectations:

- terminal stderr contains analysis tool calls and a normal model completion;
- traces must not contain a model call to `grid_submit_answer`;
- `turns/NNN/answer-draft.json` is controller-generated;
- failed turns preserve their tool results in `report.md`;
- any failed required turn produces status `failed` and exit code `1`.

Update architecture diagrams so the terminal transition is “model final text →
controller commit”, not “LLM calls submission tool”. Do not rewrite historical
files under `docs/superpowers/specs/` or `docs/superpowers/plans/`.

Append an architectural decision to `docs/status/DECISIONS.md` recording the
controller-owned submission choice, its provider-independence rationale, the
evidence-first report consequence, and links to the approved specification and
this plan. `DECISIONS.md` already has an INDEX entry, so no INDEX edit is needed.

- [ ] **Step 3: Check for stale current-document claims**

Run:

```bash
rg -n "grid_submit_answer|must call|必须调用|调用.*提交" \
  AGENTS.md configs/agent skills/grid-static-analysis \
  docs/RUNBOOK.md docs/MANUAL-VALIDATION.md docs/architecture
```

Expected: no current instruction tells the model to call
`grid_submit_answer`; historical compatibility notes may describe old run
events only when explicitly labeled historical.

- [ ] **Step 4: Run focused static and contract verification**

Run:

```bash
git diff --check
npm run check --prefix packages/pi-grid-tools
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/contract \
  packages/grid-agent/tests/analysis \
  packages/grid-agent/tests/runtime \
  packages/grid-agent/tests/cli -q
```

Expected: no whitespace errors; Node syntax check and all focused Python tests
pass.

- [ ] **Step 5: Run the full offline gates**

Run in this order:

```bash
make doctor
make test
make test-e2e
make validate
```

Expected:

- `make doctor`: exits `0` and reports the resolved `gridctl` path.
- `make test`: exits `0` for agent, simulator, Pi-grid-tools, and workbench-independent tests.
- `make test-e2e`: exits `0`; scripted providers use ordinary final text.
- `make validate`: exits `0` for offline TASK, scripted static core, scripted full capability, and capability-matrix checks.

Do not run `make validate-provider`.

- [ ] **Step 6: Commit documentation and any gate-driven corrections**

Stage only the owned source, test, and documentation files shown by
`git status --short`, excluding pre-existing user PDFs, ZIPs, scripts, question
files, and unrelated status edits:

```bash
git add AGENTS.md configs/agent/system-policy.md \
  skills/grid-static-analysis docs/RUNBOOK.md docs/MANUAL-VALIDATION.md \
  docs/architecture/analysis-context.md \
  docs/architecture/pandapower-capability-composition.md \
  docs/status/DECISIONS.md
git commit -m "docs: document controller-owned answer submission"
```

If a gate required a source/test correction after Task 4, commit that correction
separately before the documentation commit with a message describing the fixed
regression.

- [ ] **Step 7: Verify repository and branch closure**

Run:

```bash
git status --short
git log --oneline -8
git worktree list
git branch --show-current
```

Expected: branch is `main`; no task-created worktree or temporary branch
remains; only the user's pre-existing uncommitted/untracked files remain. Do
not push or move `v1.0.0` unless the user separately requests it.

---

## Final acceptance checklist

- [ ] No model-visible tool or prompt requires `grid_submit_answer`.
- [ ] Online `run` and continuous `analysis` publish ordinary model final text through controller-owned paths.
- [ ] Continuous answer artifacts contain controller-derived current-turn result/evidence lineage and empty structured claims.
- [ ] Empty final text fails the turn and batch.
- [ ] A failed required turn can never coexist with a newly emitted `analysis.completed`.
- [ ] Main reports render every recorded tool result before model prose.
- [ ] Failed-turn reports preserve successful tool values.
- [ ] Integrity diagnostics do not semantically re-evaluate simulator facts.
- [ ] CLI stdout remains exactly one JSON object.
- [ ] `make doctor`, `make test`, `make test-e2e`, and `make validate` pass without a billed provider call.
- [ ] Work ends on `main` without a temporary worktree or branch.
