# Projection Import Task 1 — Re-review Fix 2

## Scope

Addressed the two Important findings against `eb04c1a` in:

- `packages/grid-agent/src/grid_agent/trajectory/projection_models.py`
- `packages/grid-agent/tests/trajectory/test_service.py`

## Changes

- Made `rule_id` shared `ProjectionNode` provenance. Every derived projection now
  requires an explicit, nonempty rule ID as well as positive source sequences;
  non-derived projections reject rule IDs.
- Deep-froze `ArtifactIndex.records` with the existing JSON-compatible immutable
  mapping implementation.

## TDD Evidence

The focused test was first run after adding coverage and failed because default
derived `ContextFrame` / `ProjectionDiagnostic` objects accepted no `rule_id`,
and `ArtifactIndex.records` accepted mutation. The minimal model changes made
that test pass.

## Verification

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py -q` — 13 passed
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q` — 125 passed
- `uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/src/grid_agent/trajectory/replay.py packages/grid-agent/tests/trajectory/test_service.py` — passed
- `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/src/grid_agent/trajectory/replay.py packages/grid-agent/tests/trajectory/test_service.py` — 0 errors
