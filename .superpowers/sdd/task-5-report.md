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

## Concerns

- None known.
