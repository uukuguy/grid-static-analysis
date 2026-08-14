# Native Capture Task 2 Report: Python runtime capture adapter

Date: 2026-08-14

Status: implemented and verified

## Scope

Implemented the approved Task 2 native runtime capture boundary only:

- Added `NativeCaptureAdapter` with one-active-turn state, monotonic request
  discovery, exact request/response artifact admission, request timing, retry
  mapping, and identity-keyed tool lifecycle capture.
- Added `PiRpcClient.prompt_and_wait(..., capture=...)` ordering so provider
  request sidecars are drained before raw response handling, native raw capture
  precedes legacy progress callbacks, and native semantic capture precedes the
  legacy semantic callback.
- Removed RPC tool pairing by adjacency or tool-name fallback. Pending tool
  metadata is now keyed and consumed only by `tool_call_id`.
- Preserved streaming-delta exclusion, hidden-reasoning exclusion, restricted
  runtime capabilities, and the existing answer/stdout behavior.

## Files

- `packages/grid-agent/src/grid_agent/trajectory/capture.py` (new)
- `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- `packages/grid-agent/tests/trajectory/test_capture.py` (new)
- `packages/grid-agent/tests/runtime/test_rpc.py`

## TDD evidence

### RED

After adding the capture and RPC contract tests, ran:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py -q
```

Observed the expected pre-implementation collection failure:

```text
ModuleNotFoundError: No module named 'grid_agent.trajectory.capture'
2 errors in 0.17s
```

This proved both the new adapter surface and RPC integration were absent.

### GREEN

Focused command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py -q
```

Observed result:

```text
.....................                                                    [100%]
21 passed in 0.48s
```

Broader related command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory \
  packages/grid-agent/tests/runtime -q
```

Observed result:

```text
........................................................................ [ 55%]
..........................................................               [100%]
130 passed in 0.66s
```

Also run:

```sh
git diff --check
```

Observed result: success with no whitespace errors.

## Deterministic mapping implemented

- `begin_turn` refuses overlapping turns; `end_turn` records an unsettled
  provider request as `model.response.failed` with interruption identity.
- Request sidecars are schema-checked, turn-bound, monotonically indexed,
  admitted without byte changes through `register_existing`, and appended as
  `model.request.started`. Their last `source_event_sequences` value is stored
  as causation, never as an artifact reference.
- Text deltas and assistant message-update deltas only set the in-memory
  first-token clock. They never append native events or artifacts.
- Assistant `message_end` filters the public text blocks, excludes all thinking
  blocks, commits a `model-response` artifact first, and then appends
  `model.response.completed` with usage, TTFT, and duration summaries.
- Failed prompt acknowledgements and provider-error `agent_end` observations
  append `model.response.failed` without copying raw provider records.
- `auto_retry_start` maps attempt, maximum, delay, and public error text to
  `model.retry.started`. Only unsuccessful terminal `auto_retry_end` maps to
  `model.retry.exhausted`; successful settlement emits no exhausted event.
- Tool starts require `tool_call_id`, reject unsafe argument fields, persist
  their bounded invocation arguments through the registered `tool-result`
  layout, and append `tool.started` only after artifact admission.
- Tool completions require an exact live `tool_call_id`, may settle in any
  order, reverify the invocation artifact, verify and register current-run
  result/evidence documents, then append `tool.completed`. Missing or unknown
  identity raises `CaptureIntegrityError`; no positional or name inference is
  used.

## Boundary review

- No raw request payload, provider record, streaming delta, private reasoning,
  credential field, shell surface, generic file capability, or simulator object
  is copied into the native event stream.
- Exact provider request files are admitted in place; exact public response
  artifacts and tool invocation artifacts are registered before dependent
  events.
- The RPC return value and stdout contract are unchanged.
- Pre-existing unrelated edits in `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` were left untouched.

## Concern for downstream integration

The approved Task 2 contract requires tool-start arguments to occupy the
immutable `tool-result` registry path. The current compatibility
`AnalysisContextProjector._append_observation` later replaces that same path
with a projection document. Task 2 does not own that projector, so it was not
changed here. Before the Task 3/5 live integration gate, the compatibility
projector must stop replacing the registered native artifact (or the approved
artifact layout must be revised); otherwise later digest verification will
correctly detect tampering.
