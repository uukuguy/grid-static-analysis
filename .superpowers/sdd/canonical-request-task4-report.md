# Canonical Request Task 4 Report

## Scope

Implemented Task 4 migration only:

- Migrated scripted/current request producers to `grid-model-request-input/2.0`.
- Added commit acknowledgement participation before provider work in scripted analysis.
- Preserved historical v1 request artifacts as read-only exact bytes.
- Added normalized Context request preview that exposes only semantic request, correlations, runtime identity, and digest.
- Updated trajectory architecture, analysis context, workbench operator, and manual validation docs.

Did not remove old provider capture symbols wholesale; legacy provider-payload references remain where they are historical fixtures or redaction tests.

## Verification

- Focused RED/GREEN API preview:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py::test_context_detail_exposes_only_canonical_request_preview -q`
  - RED: failed with missing `request_input`.
  - GREEN: passed.
- Focused API historical/current request tests:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py::test_context_detail_exposes_only_canonical_request_preview packages/grid-agent/tests/trajectory/api/test_app.py::test_native_api_verifies_simulator_artifacts_and_downloads_exact_bytes packages/grid-agent/tests/trajectory/api/test_app.py::test_native_api_reads_historical_v1_request_without_mutating_bytes -q`
  - Result: 3 passed.
- Focused scripted semantic path:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/e2e/test_semantic_pi_path.py::test_scripted_pi_non_blocking_audit_keeps_topology_answer_in_run_and_batch_outputs -q`
  - Result: 1 passed.
- Focused continuous native trajectory:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/e2e/test_continuous_analysis.py::test_scripted_analysis_writes_replayable_native_trajectory -q`
  - Result: 1 passed.
- Required Task 4 command:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory packages/grid-agent/tests/e2e/test_semantic_pi_path.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q`
  - Result: 239 passed, 1 warning.
- Broader gate:
  - `make test`
  - Result: grid-agent 543 passed, grid-simulator 87 passed, pi-grid-tools 32 passed.

## Notes

- `grid-agent run` does not launch native request capture, so the semantic-path script remains capture-optional. When request capture env exists, it writes v2 and waits for commit ack; otherwise it preserves the existing non-capture behavior.
- Continuous analysis exports the project `.grid-agent/trajectory-acks/<analysis_id>/` path to Pi and now passes the same path into `NativeCaptureAdapter`, avoiding mismatched ack roots for custom artifact roots.
- Scripted producers now write request artifacts via atomic temp-file replacement to avoid capture reading partial JSON.
