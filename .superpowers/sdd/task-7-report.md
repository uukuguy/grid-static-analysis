# Task 7 Report: Bounded context view and turn-bound domain tools

## Summary

Implemented Task 7.

- Added `grid_agent.analysis.view` with deterministic bounded context views:
  - `build_context_view(context)`
  - `materialize_context_view(context, path)`
  - `ContextViewTooLarge`
- Extended Pi runtime environment paths with optional Analysis-only paths:
  - `GRID_AGENT_ACTIVE_TURN`
  - `GRID_AGENT_ANALYSIS_CONTEXT_VIEW`
- Added optional read-only Pi tool:
  - `grid_analysis_context_get`
- Updated `grid_submit_answer` so Analysis launches read `active-turn.json` at submit time and bind drafts to the active `turn_id` and `turn_nonce`.
- Preserved legacy single-run behavior when the new Analysis paths are unset.

## TDD evidence

RED:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_view.py packages/grid-agent/tests/runtime/test_pi_config.py -q && npm test --prefix packages/pi-grid-tools
```

Result: failed during Python collection with `ModuleNotFoundError: No module named 'grid_agent.analysis.view'`, matching the missing Task 7 interface.

GREEN focused verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_view.py packages/grid-agent/tests/runtime/test_pi_config.py -q && npm run check --prefix packages/pi-grid-tools && npm test --prefix packages/pi-grid-tools
```

Result:

- Python: `9 passed`
- Node syntax check: passed
- Node tests: `14 pass`

Broader verification:

```sh
make test
```

Result:

- grid-agent tests: `209 passed`
- grid-simulator tests: `79 passed, 18 warnings`
- pi-grid-tools syntax check: passed
- pi-grid-tools tests: `14 pass`

## Notes

- The context view keeps provenance identifiers and compact verified facts but drops known large simulator/result arrays such as `branch_results`.
- The view raises `ContextViewTooLarge` if the provenance-preserving view exceeds 64KB instead of silently truncating references.
- `grid_analysis_context_get` is registered only when `GRID_AGENT_ANALYSIS_CONTEXT_VIEW` is configured.
- `grid_submit_answer` keeps the previous unbound JSON draft shape for legacy launches with unset Analysis paths.
- Pre-existing unrelated workspace changes were left untouched.
