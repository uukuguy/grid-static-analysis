# Projection Import Task 2 Review Fix

## Changes

- Project claims only when an `answer.submitted` event has the same `submission_id`; the claim records both declaration and accepting submission sequences.
- Emit verified-result nodes only for completed `analysis.*` or `result.*` capabilities, and require every included reference to resolve to a `gridctl` artifact with `verified` integrity.
- On a closed analysis boundary, interrupt every unterminated turn and its open descendants.

## TDD evidence

The added focused tests were run before implementation and failed in the expected places: open turns stayed running after analysis closure; unmatched claims appeared; a mixed verified/tampered reference was accepted; and `grid_guide_open` emitted a verified result. After the reducer changes, focused projection tests pass.

## Verification

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/projections/test_business.py -q` — 10 passed
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q` — 135 passed
- `uv run --project packages/grid-agent ruff check …` — passed
- `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory/agent_projection.py packages/grid-agent/src/grid_agent/trajectory/business_projection.py` — 0 errors

Pyright over the test modules continues to report existing fixture/protocol mutability incompatibilities: the frozen test `Event` fixtures cannot implement writable `ReplayEventLike` protocol attributes. Production-target pyright passes; this fix does not change the protocol outside assigned ownership.
