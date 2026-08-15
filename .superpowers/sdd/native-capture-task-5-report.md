# Native Capture Task 5 Report: Analysis lifecycle composition

Date: 2026-08-14

Status: implemented and verified

## Scope

- Constructed one shared `ImmutableArtifactRegistry`, `RunEventRecorder`,
  `NativeContextBridge`, and `NativeCaptureAdapter` before context-store
  initialization in the Analysis CLI path.
- Registered the artifact registry and resolved credential secret with the
  recorder; only public provider/model identifiers are exposed to Pi capture.
- Passed native request, capture-state, allowed-ref, provider, and model values
  through `RuntimePaths`, and passed the shared recorder to `TurnController`.
- Published controller-known non-artifact refs atomically for bounded decision
  validation during a live turn.
- Passed capture/bridge into `AnalysisRunner`, closed the recorder in Pi's
  `finally` boundary, and retained an outer construction-failure close guard.
- Required a failure-free native replay ending in `analysis.completed` before
  publishing a completed manifest.
- Prevented `analysis.failed` appends after native replay is already unhealthy,
  preserving the reader's last valid prefix.
- Added `events_path: "events/run-events.jsonl"` and
  `trajectory_schema_version: "grid-run-event/1.0"` to native manifests.
- Kept the stdout contract at exactly one JSON object containing only
  `question_id` and `answer_output`.
- Preserved native immutable tool invocation sidecars. Compatibility projector
  results remain under the disjoint `compatibility/` directory, and reports
  prefer that projection while retaining a legacy-path fallback.

## TDD evidence

### RED

CLI/E2E command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/cli/test_app.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py -q
```

Observed expected failure: the scripted Analysis produced no native events, so
the assertion that the first event was `analysis.started` failed on an empty
trusted prefix (`1 failed, 21 passed`).

Runner command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_runner.py -q
```

Observed three expected failures: the recorder remained writable after Pi
shutdown, failure cleanup appended after a corrupted log, and corruption after
`analysis.completed` still allowed a completed manifest.

### GREEN

Focused native and Node gate:

```text
190 Python tests passed in 25.23s
24 Node tests passed
```

Report compatibility regression:

```text
12 passed
```

Changed production and new runner/E2E typing scope:

```text
pyright: 0 errors, 0 warnings, 0 informations
```

Full offline gate:

```text
grid-agent: 393 passed
grid-simulator: 87 passed (18 upstream pandapower deprecation warnings)
pi-grid-tools: syntax check passed; 24 passed
```

Deterministic validation:

```text
offline task-required: 8/8 passed
scripted-pi static-analysis-core: 10/10 passed
```

`git diff --check` passed.

## Live integration proof

The scripted Analysis gate verifies that:

- the trusted native prefix begins with `analysis.started` and ends with
  `analysis.completed`;
- model request, tool completion, and accepted-answer events are present;
- provider request sidecars contain the resolved public `openai` / `gpt-5.5`
  identifiers and neither sidecars nor events contain the provider secret;
- the manifest publishes the native event path and schema version;
- native invocation bytes remain unchanged after compatibility projection;
- compatibility observations use a different path and the generated trace page
  links that compatibility result; and
- stdout remains the two-field, one-line answer envelope with no trajectory
  payload.

## Concerns

- A pyright invocation that also included the whole existing
  `packages/grid-agent/tests/cli/test_app.py` reported five pre-existing errors
  at lines 212–219. Those lines are outside this task's edits. Production plus
  the new runner/E2E scope is clean under pyright.
- Pre-existing worktree edits in `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` were preserved and excluded from this task's commit.
- No provider-backed validation was run because it is optional, billed, and
  requires explicit credentials.
