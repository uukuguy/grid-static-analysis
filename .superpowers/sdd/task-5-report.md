# Task 5 Report: Compact semantic RPC events

## Summary

- Added `on_semantic_event` to `PiRpcClient.prompt_and_wait`.
- Replaced raw standard Pi traces with compact semantic payloads for prompt acknowledgements, tool starts, tool results, agent end status, and assembled assistant messages.
- Filtered streaming/text-growth events from the standard trace, including `text_delta`, reasoning/message-update deltas, raw `message_update` snapshots, and raw `agent_end.messages`.
- Preserved raw `on_event` callbacks for existing CLI progress and simulator-reference admission.
- Added stable tool-call pairing metadata (`tool_call_id`, `tool_name`) across tool start/result events.

## TDD Evidence

- RED: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py -q`
  - Failed because `prompt_and_wait` did not yet accept `on_semantic_event`.
- GREEN: implemented semantic normalization/filtering and updated legacy trace assertions for the compact shape.

## Verification

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py packages/grid-agent/tests/test_trace.py -q`
  - 13 passed.
- Review fix:
  - `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py packages/grid-agent/tests/test_trace.py -q`
    - 13 passed.
  - `uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/runtime/test_rpc.py`
    - All checks passed.
  - `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/runtime/test_rpc.py`
    - 0 errors, 0 warnings.
  - `uv run --project packages/grid-agent mypy --ignore-missing-imports packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/runtime/test_rpc.py`
    - Success: no issues found in 2 source files.

## Concerns

- None known.

## Regression Gate Fix

- Status: resolved with a documentation-only wording change in the trajectory capture plan; the plan remains operative.
- Commit: `e41874b` (`docs: fix task 5 boundary verification wording`).
- Tests: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/contract/test_repository_boundaries.py -q` — 6 passed; `git diff --check` — passed.
- Concerns: none known; the pre-existing `docs/status/JOURNAL.md` modification was left untouched.

## Completion

- Delivered `grid-agent trajectory serve` and `make trajectory PORT=8765` with
  loopback-only binding, stderr-only startup failures, and no answer envelope.
- Closed the API review gaps: request-validation responses are typed and carry
  every browser security header; artifact bytes are read through a
  descriptor-relative `O_NOFOLLOW` chain, `fstat`-verified, and hashed from the
  same descriptor.
- Focused verification: trajectory API 48 passed, CLI 21 passed, `make doctor`
  passed, ruff passed, and task-scoped pyright reported 0 errors.
- Broad `pyright packages/grid-agent/src` remains red only for 29 pre-existing
  errors outside this task's files (`config/catalog.py`, `knowledge/offline.py`,
  `reporting.py`, and `validation/oracles.py`).
