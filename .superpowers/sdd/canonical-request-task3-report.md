# Task 3 Report: Python Recorder Canonical Request Commit

## Scope

Implemented the Python recorder/RPC slice for canonical request commit acknowledgements only.

## Changes

- `packages/grid-agent/src/grid_agent/trajectory/capture.py`
  - Added `drain_model_requests()` for schema `grid-model-request-input/2.0`.
  - Centralized canonical request parsing in `CanonicalModelRequestDocument`.
  - Recomputes `semantic_request_sha256` from `semantic_request`; supplied digest is only shape-validated.
  - Validates closed runtime, model, context, message, tool, and public options shapes.
  - Registers the immutable request artifact, appends `model.request.started`, then publishes `grid-model-request-commit/1.0` ack with artifact ref and event sequence.
  - Uses temp-file plus exclusive hard-link publication for ack visibility and conflict detection.
  - Defers next request ingestion while a `toolUse` response has queued tool events to preserve request attribution.

- `packages/grid-agent/src/grid_agent/runtime/rpc.py`
  - Polls `capture.drain_model_requests()` immediately after prompt send.
  - Polls on stdout queue timeouts, capped at 25 ms while preserving configured heartbeat cadence.
  - Polls before decoded RPC event handling and before terminal event returns/raises.
  - Updated capture-fatal marker to `trajectory model request commit failed`.

- `packages/grid-agent/tests/trajectory/test_capture.py`
  - Replaced provider-payload request fixtures with canonical schema `2.0`.
  - Added digest recomputation, ack ordering, idempotence, malformed-no-ack, and provider/model state assertions.

- `packages/grid-agent/tests/runtime/test_rpc.py`
  - Added blocking fake-Pi coverage proving provider continuation waits for Python commit ack.
  - Added multi-round tool-call coverage with one request artifact/start event per provider invocation.
  - Added capture-failure coverage proving malformed input prevents provider fixture continuation.

## Verification

- Red test observed before implementation:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py -q`
  - Failed with missing `drain_model_requests()` and blocked RPC commit polling.

- Focused required tests:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py -q`
  - `29 passed in 0.66s`

- Compile diagnostics fallback:
  - `uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/trajectory/capture.py packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/runtime/test_rpc.py`
  - Passed with no output.

- Broader non-e2e gate:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests --ignore=packages/grid-agent/tests/e2e -q`
  - `524 passed, 1 warning in 20.34s`

- Full `make test`:
  - `537 passed, 4 failed, 1 warning in 58.85s`
  - The four failures are scripted e2e fixtures still writing legacy `grid-model-request-input/1.0`; left unchanged per Task 3 boundary and instruction not to perform historical/API migration.

## Notes

- No provider payload normalization or provider payload fields are accepted by the Python recorder.
- Existing unrelated dirty files were left untouched:
  - `.superpowers/sdd/task-1-report.md`
  - `.superpowers/sdd/task-2-report.md`
  - `docs/status/JOURNAL.md`
