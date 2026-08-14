# Native Trajectory Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new continuous Analysis runs write complete native lifecycle, exact model-request, public response, retry, tool, context, decision, claim, answer, and audit events to the verified event spine.

**Architecture:** Pi's pinned `before_provider_request` hook atomically captures the exact provider payload before the HTTP call; capture failure exits the restricted Pi child before the provider request can proceed. Python drains those immutable request sidecars before processing each subsequent RPC event and remains the sole event-log writer. Existing context ledgers become compatibility outputs because every context transition commits its native event first.

**Tech Stack:** Python 3.12+, Pydantic 2.12, Pi RPC JSONL, `@earendil-works/pi-coding-agent` 0.80.6 extension hooks, Node.js 22.19+, grid-capability 1.0, pandapower 3.4.0, pytest 9, Node test runner.

## Global Constraints

- `RunEventRecorder` from the event-spine plan is the only `run-events.jsonl` writer.
- `before_provider_request` captures the exact provider payload and fsyncs `requests/<request_id>/input.json` before returning.
- The Node extension writes request/decision/answer sidecars only; it never writes or edits the authoritative event log.
- Request-capture failure terminates Pi with exit code 86; Python reports a terminal recorder/capture integrity failure and produces no successful answer.
- Streaming text/reasoning deltas are not persisted as events; they may update in-memory TTFT counters only.
- Complete public assistant messages, tool calls/results, retries, usage, timing, and errors are captured.
- `grid_record_decision` is bounded agent intent, never simulator truth; missing decisions are not inferred.
- Simulator-backed `claims[]` use verified current-run result/evidence refs; answer prose is never parsed into claims.
- Proposed claims become accepted only when a matching `answer.submitted` with the same `submission_id` exists.
- Compatibility `context/context-events.jsonl` and `trace/events.jsonl` remain available but are written only after the corresponding native event is durable.
- The stdout answer envelope and all existing gridctl/evidence/report contracts remain unchanged.
- Use red/green TDD, focused tests first, and one atomic commit per task.

## File Map

### New production files

- `packages/pi-grid-tools/src/trajectory-capture.mjs` — exact provider-request capture, fsync, and fatal capture semantics.
- `packages/grid-agent/src/grid_agent/trajectory/capture.py` — Pi/RPC-to-native event state machine.
- `packages/grid-agent/src/grid_agent/trajectory/context_bridge.py` — native-before-compatibility context transition hook.
- `packages/grid-agent/src/grid_agent/trajectory/answers.py` — typed decisions/claims and submission validation helpers.

### Modified production files

- `packages/pi-grid-tools/src/domain-tools.mjs` — register capture hook, `grid_record_decision`, and structured `claims[]`.
- `packages/grid-agent/src/grid_agent/runtime/environment.py` — expose request/capture-state paths and public provider/model identifiers.
- `packages/grid-agent/src/grid_agent/runtime/rpc.py` — drain request capture before raw events and report full public lifecycle to `NativeCaptureAdapter`.
- `packages/grid-agent/src/grid_agent/analysis/store.py` — native-before-compatibility transition callback.
- `packages/grid-agent/src/grid_agent/analysis/turns.py` — structured claim validation and submission-correlated events.
- `packages/grid-agent/src/grid_agent/analysis/runner.py` — native lifecycle, context injection, terminal capture failure, and final replay verification.
- `packages/grid-agent/src/grid_agent/analysis/workspace.py` — capture-state and allowed-ref paths.
- `packages/grid-agent/src/grid_agent/cli/app.py` — construct recorder, bridge, adapter, and secret filters.
- `packages/grid-agent/src/grid_agent/tools/catalog.py` — publish the bounded decision tool description alongside non-simulator tools.
- `packages/grid-agent/src/grid_agent/runtime/pi_config.py` — no new capability; verify request metadata does not expose secrets.
- `packages/grid-agent/src/grid_agent/analysis/report.py` — continue reading compatibility trace while accepting native sequence links.

### Tests

- `packages/pi-grid-tools/test/trajectory-capture.test.mjs`
- `packages/pi-grid-tools/test/domain-tools.test.mjs`
- `packages/grid-agent/tests/trajectory/test_capture.py`
- `packages/grid-agent/tests/trajectory/test_context_bridge.py`
- `packages/grid-agent/tests/trajectory/test_answers.py`
- `packages/grid-agent/tests/runtime/test_rpc.py`
- `packages/grid-agent/tests/runtime/test_pi_config.py`
- `packages/grid-agent/tests/analysis/test_store.py`
- `packages/grid-agent/tests/analysis/test_turns.py`
- `packages/grid-agent/tests/analysis/test_runner.py`
- `packages/grid-agent/tests/cli/test_app.py`
- `packages/grid-agent/tests/e2e/test_continuous_analysis.py`

---

### Task 1: Exact pre-provider request capture

**Files:**
- Create: `packages/pi-grid-tools/src/trajectory-capture.mjs`
- Create: `packages/pi-grid-tools/test/trajectory-capture.test.mjs`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Modify: `packages/grid-agent/tests/runtime/test_pi_config.py`

**Interfaces:**
- Produces: `configureTrajectoryCapture(pi, paths, fatal = captureFatal) -> void`.
- Adds `RuntimePaths.trajectory_requests_path`, `trajectory_capture_state_path`, `trajectory_allowed_refs_path`, `provider_id`, and `model_id`.
- Adds environment keys `GRID_AGENT_TRAJECTORY_REQUESTS`, `GRID_AGENT_TRAJECTORY_CAPTURE_STATE`, `GRID_AGENT_TRAJECTORY_ALLOWED_REFS`, `GRID_AGENT_PROVIDER_ID`, and `GRID_AGENT_MODEL_ID` only for native Analysis launches.
- Captured document schema: `grid-model-request-input/1.0` with `request_id`, `request_index`, `turn_id`, `provider`, `model`, `captured_at`, `source_event_sequences`, `context_revision`, `context_state_hash`, and exact `provider_payload`.

- [ ] **Step 1: Write failing Node and Python environment tests**

```javascript
test("captures exact provider payload before the hook returns", async () => {
  const root = await makeTrajectoryFixture();
  const handlers = new Map();
  configureTrajectoryCapture({ on: (name, handler) => handlers.set(name, handler) }, fixturePaths(root));

  const payload = { model: "deepseek-v4-flash", messages: [{ role: "user", content: "Q7" }], tools: [] };
  await handlers.get("before_provider_request")({ type: "before_provider_request", payload });

  const request = JSON.parse(await readFile(join(root, "requests/analysis-test-t007-r001/input.json"), "utf8"));
  assert.equal(request.schema_version, "grid-model-request-input/1.0");
  assert.equal(request.request_id, "analysis-test-t007-r001");
  assert.deepEqual(request.provider_payload, payload);
  assert.deepEqual(request.source_event_sequences, [40, 41]);
  assert.equal(request.context_revision, 59);
});


test("capture failure invokes fatal exit before returning", async () => {
  const handlers = new Map();
  const failures = [];
  configureTrajectoryCapture(
    { on: (name, handler) => handlers.set(name, handler) },
    { ...fixturePaths(await makeTrajectoryFixture()), requestsPath: "/unwritable/missing" },
    (message) => { failures.push(message); throw new Error("fatal-86"); },
  );

  await assert.rejects(
    handlers.get("before_provider_request")({ type: "before_provider_request", payload: {} }),
    /fatal-86/,
  );
  assert.match(failures[0], /trajectory request capture failed/);
});
```

```python
def test_pi_launch_exposes_native_capture_paths_only_when_configured(tmp_path: Path) -> None:
    native = replace(
        _runtime_paths(tmp_path),
        trajectory_requests_path=tmp_path / "run/requests",
        trajectory_capture_state_path=tmp_path / "run/context/trajectory-capture-state.json",
        trajectory_allowed_refs_path=tmp_path / "run/context/trajectory-allowed-refs.json",
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
    )
    launch = build_pi_launch(_resolved_openai(), native, base_environment={"PATH": "/bin", "HOME": "/tmp"})
    assert launch.environment["GRID_AGENT_TRAJECTORY_REQUESTS"] == str(native.trajectory_requests_path)
    assert launch.environment["GRID_AGENT_PROVIDER_ID"] == "deepseek"
    assert "super-secret" not in json.dumps({key: value for key, value in launch.environment.items() if key.startswith("GRID_AGENT_TRAJECTORY")})
```

- [ ] **Step 2: Run and confirm failures**

Run: `npm test --prefix packages/pi-grid-tools -- --test-name-pattern="capture" && uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_pi_config.py -q`

Expected: FAIL because the capture module and native `RuntimePaths` fields do not exist.

- [ ] **Step 3: Implement atomic hook capture and fail-closed exit**

```javascript
export function configureTrajectoryCapture(pi, paths, fatal = captureFatal) {
  let requestIndex = 0;
  pi.on("before_provider_request", async (event) => {
    try {
      requestIndex += 1;
      const turn = await readJson(paths.activeTurnPath);
      const state = await readJson(paths.captureStatePath);
      const requestId = `${turn.turn_id}-r${String(requestIndex).padStart(3, "0")}`;
      const document = {
        schema_version: "grid-model-request-input/1.0",
        request_id: requestId,
        request_index: requestIndex,
        turn_id: turn.turn_id,
        provider: paths.providerId,
        model: paths.modelId,
        captured_at: new Date().toISOString(),
        source_event_sequences: state.source_event_sequences,
        context_revision: state.context_revision,
        context_state_hash: state.context_state_hash,
        provider_payload: event.payload,
      };
      await writeJsonAtomicFsync(join(paths.requestsPath, requestId, "input.json"), document);
      return undefined;
    } catch (error) {
      return fatal(`trajectory request capture failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  });
}


export function captureFatal(message) {
  process.stderr.write(`${message}\n`);
  process.exit(86);
}
```

`writeJsonAtomicFsync` opens a same-directory temporary file with `wx`, writes compact sorted JSON plus newline, calls `filehandle.sync()`, closes, renames, opens the parent directory read-only, and syncs it. Reject an existing request path, unsafe turn IDs, missing/invalid capture state, non-JSON payload values, and any key matching credential-name patterns. Import and call `configureTrajectoryCapture` from `domainToolsExtension` only when all three trajectory paths exist.

- [ ] **Step 4: Run focused tests**

Run: `npm test --prefix packages/pi-grid-tools -- --test-name-pattern="capture" && uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_pi_config.py -q`

Expected: capture ordering, fatal failure, unsafe path, secret-key rejection, and environment tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/pi-grid-tools/src/trajectory-capture.mjs packages/pi-grid-tools/src/domain-tools.mjs packages/pi-grid-tools/test/trajectory-capture.test.mjs packages/grid-agent/src/grid_agent/runtime/environment.py packages/grid-agent/tests/runtime/test_pi_config.py
git commit -m "feat: capture exact Pi provider requests"
```

### Task 2: Python native capture state machine

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/capture.py`
- Create: `packages/grid-agent/tests/trajectory/test_capture.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- Modify: `packages/grid-agent/tests/runtime/test_rpc.py`

**Interfaces:**
- Produces: `NativeCaptureAdapter(recorder, artifacts, workspace, *, clock=time.monotonic)`.
- Produces: `.begin_turn(turn_id)`, `.drain_provider_requests()`, `.on_raw_event(event)`, `.on_semantic_event(event, trace_sequence)`, and `.end_turn()`.
- `PiRpcClient.prompt_and_wait(..., capture: NativeCaptureAdapter | None = None)` drains before each decoded raw event, calls `on_raw_event` before legacy progress callbacks, and calls `on_semantic_event` after semantic normalization.
- State identity: one active turn, monotonically discovered request indexes, one current request, tool-call map keyed by `tool_call_id`, and in-memory first-token time.

- [ ] **Step 1: Write failing capture/RPC tests**

```python
def test_capture_orders_request_response_and_tool_events(tmp_path: Path) -> None:
    recorder, adapter = native_capture_fixture(tmp_path)
    adapter.begin_turn("analysis-test-t001")
    write_request_input(tmp_path, request_id="analysis-test-t001-r001", index=1)

    adapter.drain_provider_requests()
    adapter.on_semantic_event({"type": "tool_execution_start", "tool_call_id": "call-1", "tool_name": "grid_context_open", "args": {}}, 10)
    adapter.on_semantic_event({"event": "tool_result", "tool_call_id": "call-1", "capability": "context.open", "ok": True, "result": {}, "evidence_refs": []}, 11)
    adapter.on_raw_event({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}], "usage": {"input": 10, "output": 3}}})

    events = RunEventReader(recorder.events_path).read_prefix().events
    assert [event.event_type for event in events] == [
        "model.request.started", "tool.started", "tool.completed", "model.response.completed"
    ]
    assert events[1].scope.request_id == "analysis-test-t001-r001"
    assert events[2].scope.tool_call_id == "call-1"


def test_stream_deltas_only_update_ttft(tmp_path: Path) -> None:
    recorder, adapter = capture_with_active_request(tmp_path)
    adapter.on_raw_event({"type": "text_delta", "text": "first"})
    assert RunEventReader(recorder.events_path).read_prefix().events[-1].event_type == "model.request.started"
    adapter.on_raw_event({"type": "message_end", "message": {"role": "assistant", "content": []}})
    assert RunEventReader(recorder.events_path).read_prefix().events[-1].payload["ttft_seconds"] is not None


def test_rpc_drains_request_before_reporting_provider_response(tmp_path: Path) -> None:
    client, capture = scripted_rpc_with_capture(tmp_path)
    client.start()
    try:
        client.prompt_and_wait("question", capture=capture)
    finally:
        client.stop()
    event_types = [event.event_type for event in RunEventReader(capture.recorder.events_path).read_prefix().events]
    assert event_types.index("model.request.started") < event_types.index("model.response.completed")
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py -q`

Expected: FAIL because `NativeCaptureAdapter` and the RPC `capture` parameter do not exist.

- [ ] **Step 3: Implement deterministic event mapping**

```python
class NativeCaptureAdapter:
    def drain_provider_requests(self) -> None:
        for path in sorted(self.workspace.requests_path.glob("*/input.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            request_id = str(document["request_id"])
            if request_id in self._seen_requests:
                continue
            pointer = self.artifacts.register_existing("request-input", request_id, path)
            self._step_ordinal += 1
            self._current_request_id = request_id
            self._request_started_at[request_id] = self.clock()
            source_sequences = tuple(int(value) for value in document["source_event_sequences"])
            self.recorder.append(
                EventDraft(
                    event_type="model.request.started",
                    scope=RunScope(
                        turn_id=self._turn_id,
                        step_id=f"{self._turn_id}-s{self._step_ordinal:03d}",
                        request_id=request_id,
                    ),
                    payload={"artifact_ref": pointer.ref, "request_index": document["request_index"]},
                    causation=(
                        Causation(parent_sequence=source_sequences[-1])
                        if source_sequences else Causation()
                    ),
                    refs=EventRefs(produced=(pointer.ref,)),
                )
            )
            self._seen_requests.add(request_id)
```

Implement the complete retry and semantic mapping rules:

```python
SEMANTIC_EVENT_MAP = {
    "tool_execution_start": "tool.started",
    "tool_result": "tool.completed",
}
```

`message_end` with an assistant message writes a `model-response` artifact before `model.response.completed`. Provider/prompt errors emit `model.response.failed`. `auto_retry_start` emits `model.retry.started` with attempt/max/delay. `auto_retry_end` emits `model.retry.exhausted` only when its terminal outcome is exhausted; a successful settlement emits no exhausted event. Tool start records arguments through a `tool-result`-kind immutable capture artifact; completion verifies existing result/evidence refs before the event. Missing pair identity raises `CaptureIntegrityError`; no adjacency inference is allowed. Deltas update `_first_token_at` only.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py -q`

Expected: request, response, timing, retry, tool pairing, interruption, and delta-exclusion tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/capture.py packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py
git commit -m "feat: map Pi runtime into native trajectory"
```

### Task 3: Native-before-compatibility context and lifecycle bridge

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/context_bridge.py`
- Create: `packages/grid-agent/tests/trajectory/test_context_bridge.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/store.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/runner.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/workspace.py`
- Modify: `packages/grid-agent/tests/analysis/test_store.py`
- Modify: `packages/grid-agent/tests/analysis/test_runner.py`

**Interfaces:**
- Produces: `ContextTransitionCommit = Callable[[ContextEventDraft, AnalysisContext, AnalysisContext], RunEvent]`.
- `AnalysisContextStore.initialize(..., transition_commit=None)` and `.append(...)` calculate/validate next state, call the native commit, then append the compatibility ledger and snapshot.
- Produces: `NativeContextBridge(recorder, artifacts, workspace).commit(draft, before, after) -> RunEvent` and `.record_injection(context_view_path, context) -> RunEvent`.
- Writes `context/trajectory-capture-state.json` after every committed native/context event with latest source sequences and context revision/hash.

- [ ] **Step 1: Write failing ordering and terminal-failure tests**

```python
def test_context_transition_commits_native_event_before_legacy_ledger(tmp_path: Path) -> None:
    workspace, recorder, bridge = bridge_fixture(tmp_path)
    observed: list[str] = []
    bridge.on_native_commit = lambda _event: observed.append("native")
    store = AnalysisContextStore.initialize(
        workspace,
        input_record=INPUT,
        runtime_record=RUNTIME,
        transition_commit=bridge.commit,
    )
    observed.append("legacy" if workspace.context_events_path.exists() else "missing")
    assert observed[:2] == ["native", "legacy"]
    assert RunEventReader(recorder.events_path).read_prefix().events[0].event_type == "analysis.started"


def test_native_commit_failure_prevents_compatibility_append(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    with pytest.raises(ContextStoreError, match="native trajectory"):
        AnalysisContextStore.initialize(
            workspace,
            input_record=INPUT,
            runtime_record=RUNTIME,
            transition_commit=lambda *_args: (_ for _ in ()).throw(RecorderIntegrityError("disk full")),
        )
    assert not workspace.context_events_path.exists()


def test_runner_records_context_injection_after_artifact_write(tmp_path: Path) -> None:
    outcome, events = run_scripted_native_analysis(tmp_path)
    injected = [event for event in events if event.event_type == "context.injected"]
    assert outcome.status == "completed"
    assert injected
    assert all(event.context.before_revision == event.context.after_revision for event in injected)
    assert all(event.payload["artifact_ref"] in event.refs.produced for event in injected)
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_context_bridge.py packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/analysis/test_runner.py -q`

Expected: FAIL because transition callbacks and native context injection do not exist.

- [ ] **Step 3: Implement transition mapping and runner lifecycle wiring**

```python
CONTEXT_TO_NATIVE = {
    "analysis.started": "analysis.started",
    "analysis.completed": "analysis.completed",
    "analysis.failed": "analysis.failed",
    "turn.started": "turn.started",
    "turn.completed": "turn.completed",
    "tool.failed": "tool.failed",
    "answer.submitted": "answer.submitted",
    "audit.diagnostic.recorded": "audit.diagnostic.recorded",
}


class NativeContextBridge:
    def commit(self, draft: ContextEventDraft, before: AnalysisContext, after: AnalysisContext) -> RunEvent:
        event_type = CONTEXT_TO_NATIVE.get(draft.event_type, "context.projected")
        event = self.recorder.append(
            EventDraft(
                event_type=event_type,
                scope=RunScope(turn_id=draft.turn_id) if draft.turn_id else RunScope(),
                context=ContextBoundary(before_revision=before.revision, after_revision=after.revision),
                payload=self._payload(event_type, draft, after),
                refs=self._refs(draft),
            )
        )
        self._write_capture_state(event, after)
        return event
```

In `AnalysisContextStore.append`, run the pure reducer first, call `transition_commit`, and only then call `_append_jsonl_fsync` and `_write_json_atomic`. Store the returned native sequence in the compatibility event's existing `trace_sequence` field. In `AnalysisRunner`, call `capture.begin_turn` immediately after `TurnController.start`, pass `capture` into `prompt_and_wait`, call `capture.end_turn` after finalization, and verify `RunEventReader(...).failure is None` before `analysis.completed`. `NativeContextBridge.record_injection` registers the exact bounded context-view artifact before `context.injected`.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_context_bridge.py packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/analysis/test_runner.py -q`

Expected: native-first ordering, lifecycle, context revision, injection, terminal failure, and compatibility replay tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/context_bridge.py packages/grid-agent/src/grid_agent/analysis/store.py packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/src/grid_agent/analysis/workspace.py packages/grid-agent/tests/trajectory/test_context_bridge.py packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/analysis/test_runner.py
git commit -m "feat: make native events precede context projections"
```

### Task 4: Bounded business decisions and structured claims

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/answers.py`
- Create: `packages/grid-agent/tests/trajectory/test_answers.py`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/pi-grid-tools/test/domain-tools.test.mjs`
- Modify: `packages/grid-agent/src/grid_agent/analysis/turns.py`
- Modify: `packages/grid-agent/tests/analysis/test_turns.py`
- Modify: `packages/grid-agent/src/grid_agent/tools/catalog.py`
- Modify: `packages/grid-agent/tests/tools/test_catalog.py`

**Interfaces:**
- Adds tool `grid_record_decision(intent, decision, next_action, refs)` with text fields 1–500 chars and at most 20 known refs.
- Adds `claims[]` to `grid_submit_answer`; each item has `statement`, `category`, `result_refs`, and `evidence_refs`.
- Produces Pydantic `AnswerClaim`, `AnswerSubmission`, and `validate_submission(draft, verifier, allowed_refs) -> AnswerSubmission`.
- `TurnController.finalize` validates the complete submission before appending claim events; each claim and answer share `submission_id`.

- [ ] **Step 1: Write failing Node/Python contract tests**

```javascript
test("records bounded decisions only against controller-known refs", async () => {
  const { registered, root } = await configuredNativeTools();
  const known = "result:sha256:" + "a".repeat(64);
  await writeFile(join(root, "run/context/trajectory-allowed-refs.json"), JSON.stringify({ refs: [known] }));
  const decision = registered.find((tool) => tool.name === "grid_record_decision");

  const accepted = await decision.execute("decision-1", {
    intent: "Assess line 17 N-1 security",
    decision: "Run the published contingency capability",
    next_action: "Resolve line 17 and execute N-1",
    refs: [known],
  });
  const rejected = await decision.execute("decision-2", {
    intent: "Assess",
    decision: "Guess",
    next_action: "Answer",
    refs: ["result:sha256:" + "b".repeat(64)],
  });
  assert.equal(accepted.isError, undefined);
  assert.equal(accepted.details.capability, "grid_record_decision");
  assert.equal(rejected.isError, true);
});
```

```python
def test_turn_finalization_emits_claims_only_for_accepted_submission(tmp_path: Path) -> None:
    controller, recorder, handle, result_ref, evidence_ref = answer_fixture(tmp_path)
    write_bound_draft(handle, claims=[{
        "statement": "Line 11 reaches 132.51 percent loading",
        "category": "numerical_result",
        "result_refs": [result_ref],
        "evidence_refs": [evidence_ref],
    }])
    controller.finalize(handle, duration_seconds=1.0)
    events = RunEventReader(recorder.events_path).read_prefix().events
    claim = next(event for event in events if event.event_type == "business.claim.declared")
    answer = next(event for event in events if event.event_type == "answer.submitted")
    assert claim.payload["submission_id"] == answer.payload["submission_id"]


def test_rejected_submission_emits_no_claim_events(tmp_path: Path) -> None:
    controller, recorder, handle, _result_ref, _evidence_ref = answer_fixture(tmp_path)
    write_bound_draft(handle, claims=[{"statement": "unsupported", "category": "numerical_result", "result_refs": [], "evidence_refs": []}])
    with pytest.raises(AnswerDraftError, match="simulator-backed claim"):
        controller.finalize(handle, duration_seconds=1.0)
    assert not any(event.event_type == "business.claim.declared" for event in RunEventReader(recorder.events_path).read_prefix().events)
```

- [ ] **Step 2: Run and confirm failures**

Run: `npm test --prefix packages/pi-grid-tools -- --test-name-pattern="decision|claims" && uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_answers.py packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/tools/test_catalog.py -q`

Expected: FAIL because the decision tool, claims schema, and submission validator do not exist.

- [ ] **Step 3: Implement bounded declaration and claim acceptance**

```python
class AnswerClaim(StrictFrozenModel):
    statement: str = Field(min_length=1, max_length=1000)
    category: Literal["topology", "constraint", "numerical_result", "risk_judgment", "offline_information"]
    result_refs: tuple[str, ...] = Field(default=(), max_length=20)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def require_simulator_lineage(self) -> AnswerClaim:
        if self.category != "offline_information" and not (self.result_refs or self.evidence_refs):
            raise ValueError("simulator-backed claim requires result or evidence refs")
        return self


class AnswerSubmission(StrictFrozenModel):
    submission_id: str
    answer_output: str = Field(min_length=1)
    result_refs: tuple[str, ...]
    claim_evidence_refs: tuple[str, ...]
    claims: tuple[AnswerClaim, ...] = Field(max_length=50)
```

`validate_submission` verifies every claim ref with `ContentReferenceVerifier`, requires the union of claim result/evidence refs to be subsets of the answer-level declarations, and permits an offline-information claim only when both ref lists are empty. Node reads `trajectory-allowed-refs.json` at decision execution and returns a typed tool error for unknown refs. `TurnController.finalize` completes all validation and persists the immutable answer artifact before appending claims followed by `answer.submitted`; it emits `answer.rejected` with no proposed claim content on structural rejection.

- [ ] **Step 4: Run focused tests**

Run: `npm test --prefix packages/pi-grid-tools -- --test-name-pattern="decision|claims" && uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_answers.py packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/tools/test_catalog.py -q`

Expected: bounds, known-ref, offline, union, rejected-draft, dangling-submission, and accepted-claim tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/answers.py packages/grid-agent/tests/trajectory/test_answers.py packages/pi-grid-tools/src/domain-tools.mjs packages/pi-grid-tools/test/domain-tools.test.mjs packages/grid-agent/src/grid_agent/analysis/turns.py packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/src/grid_agent/tools/catalog.py packages/grid-agent/tests/tools/test_catalog.py
git commit -m "feat: capture business decisions and claims"
```

### Task 5: CLI composition and scripted native Analysis gate

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py`
- Modify: `packages/grid-agent/tests/e2e/test_continuous_analysis.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py`
- Modify: `docs/architecture/analysis-context.md`

**Interfaces:**
- `_execute_analysis` constructs `ImmutableArtifactRegistry`, `RunEventRecorder`, `NativeContextBridge`, and `NativeCaptureAdapter` before `AnalysisContextStore.initialize`.
- Secret values passed to the recorder include resolved provider credentials; only public provider/model IDs enter capture artifacts.
- Completed manifest adds `events_path: "events/run-events.jsonl"` and `trajectory_schema_version: "grid-run-event/1.0"`.
- Failed recorder/capture verification leaves the manifest failed and preserves the last valid event prefix.

- [ ] **Step 1: Write failing CLI/E2E assertions**

```python
def test_scripted_analysis_writes_replayable_native_trajectory(tmp_path: Path) -> None:
    result, analysis_root = run_scripted_continuous_analysis(tmp_path)
    assert result.exit_code == 0
    assert len(result.stdout.splitlines()) == 1
    prefix = RunEventReader(analysis_root / "events/run-events.jsonl").read_prefix()
    assert prefix.failure is None
    event_types = [event.event_type for event in prefix.events]
    assert event_types[0] == "analysis.started"
    assert event_types[-1] == "analysis.completed"
    assert "model.request.started" in event_types
    assert "tool.completed" in event_types
    assert "answer.submitted" in event_types
    manifest = json.loads((analysis_root / "manifest.json").read_text())
    assert manifest["events_path"] == "events/run-events.jsonl"


def test_analysis_stdout_contract_survives_native_capture(tmp_path: Path) -> None:
    result, _analysis_root = run_scripted_continuous_analysis(tmp_path)
    assert set(json.loads(result.stdout)) == {"question_id", "answer_output"}
    assert "trajectory" not in result.stdout
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q`

Expected: FAIL because `_execute_analysis` does not construct native trajectory components or expose the manifest fields.

- [ ] **Step 3: Wire composition and compatibility documentation**

```python
artifacts = ImmutableArtifactRegistry(workspace.root_path)
recorder = RunEventRecorder(
    workspace.events_path,
    workspace.analysis_id,
    secret_values={resolved.secret.value} if resolved.secret is not None else set(),
)
bridge = NativeContextBridge(recorder, artifacts, workspace)
store = AnalysisContextStore.initialize(
    workspace,
    input_record=_input_record(copied_instructions),
    runtime_record=_runtime_record(resolved.config.provider, resolved.config.model, environment_description),
    transition_commit=bridge.commit,
)
capture = NativeCaptureAdapter(recorder, artifacts, workspace)
```

Pass native paths/provider/model through `RuntimePaths`, pass `capture` and `bridge` into `AnalysisRunner`, and close the recorder in the same `finally` boundary as Pi. Before a completed manifest is written, assert a failure-free replay whose last event is `analysis.completed`; on failure append `analysis.failed` only when the recorder is still healthy. Update `analysis-context.md` to label legacy context/trace artifacts as compatibility projections for native runs.

- [ ] **Step 4: Run focused native integration tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory packages/grid-agent/tests/runtime/test_rpc.py packages/grid-agent/tests/runtime/test_pi_config.py packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/analysis/test_runner.py packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q && npm test --prefix packages/pi-grid-tools`

Expected: all native capture and Node tool tests pass; scripted Analysis has a valid event chain and unchanged one-line stdout.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/e2e/test_continuous_analysis.py packages/grid-agent/src/grid_agent/analysis/report.py docs/architecture/analysis-context.md
git commit -m "feat: enable native analysis trajectories"
```

### Task 6: Native-capture regression gate

**Files:**
- Verify only: Tasks 1–5 outputs.

**Interfaces:**
- Produces verification evidence only.

- [ ] **Step 1: Run full offline tests serially**

Run: `make test`

Expected: grid-agent, simulator, and Node suites all pass. Run serially to avoid the known gridctl resource-contention timeout from parallel gates.

- [ ] **Step 2: Run E2E and deterministic validation serially**

Run: `make test-e2e && make validate`

Expected: E2E passes; offline and scripted validation complete with no stdout-envelope or current-run evidence regression.

- [ ] **Step 3: Inspect the newest fresh scripted event chain**

Run: `uv run --project packages/grid-agent python -c 'import json; from pathlib import Path; from grid_agent.trajectory.reader import RunEventReader; paths=list(Path("runs").glob("*/events/run-events.jsonl")); path=max(paths, key=lambda item: item.stat().st_mtime_ns); prefix=RunEventReader(path).read_prefix(); print(json.dumps({"path": str(path), "failure": None if prefix.failure is None else prefix.failure.model_dump(mode="json"), "sequences": [event.sequence for event in prefix.events], "last_event": prefix.events[-1].event_type}, sort_keys=True))'`

Expected: output names the scripted analysis produced by the immediately preceding E2E run, reports `failure=null`, has contiguous `sequences`, and ends with `last_event="analysis.completed"`. Do not use provider credentials.

- [ ] **Step 4: Inspect the commit boundary**

Run: `git status --short && git log --oneline -6`

Expected: no uncommitted implementation changes; five task commits are visible. Do not create an empty verification commit.

## Self-Review

- Spec coverage: exact request input, public responses, TTFT/usage, retries, tools, native lifecycle, context revisions/injections, single-writer ordering, bounded decisions, structured claims, rejection semantics, terminal recorder failure, and compatibility outputs are covered.
- The Pi 0.80.6 hook is verified locally in the installed source tree as `before_provider_request(payload: unknown)`; the plan does not assume an undocumented message approximation.
- Deferred intentionally: projection materialization, historical importer, API, UI, and live streaming remain in later plans.
- Type consistency: the capture plan consumes exactly the event-spine interfaces and produces native logs consumed by `ProjectionService` in the next plan.
