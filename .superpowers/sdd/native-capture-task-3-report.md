# Native Capture Task 3 Report

## Outcome

Implemented the native-before-compatibility analysis-context bridge and runner
lifecycle wiring.

- `AnalysisContextStore.initialize(..., transition_commit=...)` and `append(...)`
  now reduce the next context first, commit the native event, then append the
  compatibility ledger and snapshot.
- The returned native sequence is persisted in the compatibility event's
  existing `trace_sequence` field.
- Native commit failure is wrapped as `ContextStoreError` and prevents both
  compatibility ledger and snapshot creation.
- `NativeContextBridge` maps context transitions into native events, persists
  `context/trajectory-capture-state.json`, admits answer artifacts, and records
  immutable `context.injected` artifacts with exact bounded-view bytes.
- `AnalysisRunner` begins capture immediately after turn start, passes capture
  into `prompt_and_wait`, ends capture after turn finalization, records actual
  context injections, and rejects native replay failures before
  `analysis.completed`.
- Compatibility observation sidecars now use
  `tool-results/<turn>/compatibility/<call>.json`, so they cannot replace the
  immutable native `tool-results/<turn>/<call>.json` invocation sidecar.

## TDD Evidence

RED was observed before each production behavior:

1. Store tests failed because `transition_commit` was not accepted.
2. Bridge tests failed because `NativeContextBridge` did not exist.
3. Runner tests failed because `capture` and `context_bridge` were not accepted.
4. Projector regression failed because compatibility projection replaced the
   registered native tool sidecar and invalidated its pointer.

Each slice was implemented minimally and rerun GREEN before continuing.

## Verification

Focused affected suites and lint:

```text
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_artifacts.py \
  packages/grid-agent/tests/trajectory/test_context_bridge.py \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py \
  packages/grid-agent/tests/analysis/test_projector.py \
  packages/grid-agent/tests/analysis/test_store.py \
  packages/grid-agent/tests/analysis/test_runner.py -q

88 passed in 0.97s
```

```text
uv run --project packages/grid-agent ruff check <Task 3 affected files>
All checks passed!
```

Full grid-agent regression suite:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
379 passed in 63.89s (0:01:03)
```

## Files

- Created `packages/grid-agent/src/grid_agent/trajectory/context_bridge.py`
- Created `packages/grid-agent/tests/trajectory/test_context_bridge.py`
- Modified analysis store, runner, workspace, and projector integration
- Added the revision-keyed `context-view` immutable artifact layout
- Added store, runner, projector, and artifact registry regressions

## Follow-up / Concerns

- Task 5 must construct and pass the shared `ImmutableArtifactRegistry` to both
  `RunEventRecorder` (`artifact_registry=...`) and the bridge/capture objects;
  otherwise native artifact-reference admission will fail closed.
- Task 5 still owns CLI composition, native runtime path exposure, recorder
  closure, manifest trajectory fields, and the scripted live Analysis gate.
- The mutable compatibility context view intentionally remains at
  `context/analysis-context-view.json`; native injection events reference only
  revision-keyed immutable copies under `context/views/`.

## Static Typing Follow-up

The Task 3 review's modified-scope pyright findings were resolved without
changing runtime behavior:

- Native context and semantic event mappings are explicitly typed as
  `EventType`, including the `context.projected` fallback used to construct
  `EventDraft`.
- Context-bridge and capture workspace protocols expose immutable path
  attributes through read-only properties, matching `AnalysisWorkspace`'s
  frozen dataclass contract.
- Store callback stubs now implement the actual `RunEvent` transition-commit
  signature; the artifact test narrows its optional directory descriptor before
  dictionary deletion.

Verification after the change:

```text
uv run --project packages/grid-agent pyright \
  packages/grid-agent/src/grid_agent/trajectory/context_bridge.py \
  packages/grid-agent/src/grid_agent/trajectory/capture.py \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/analysis/test_store.py \
  packages/grid-agent/tests/trajectory/test_artifacts.py

0 errors, 0 warnings, 0 informations
```

```text
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_context_bridge.py \
  packages/grid-agent/tests/analysis/test_store.py \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/trajectory/test_artifacts.py -q

51 passed in 0.59s
```
