# Task 2 Report: Typed context state and pure reducer

## Status

DONE

## Scope

Implemented the Task 2 typed, immutable in-memory analysis context model and deterministic reducer.

Created:

- `packages/grid-agent/src/grid_agent/analysis/models.py`
- `packages/grid-agent/src/grid_agent/analysis/reducer.py`
- `packages/grid-agent/tests/analysis/test_reducer.py`

No filesystem persistence, Pi integration, session resume, or model-authored factual state was added.

## Implementation details

- Added frozen Pydantic models with `extra="forbid"` for:
  - `ContextEventDraft`
  - `AnalysisContextEvent`
  - `AnalysisContext`
  - input/runtime/turn/baseline/observation/result/evidence/fact/diagnostic/limitation record models
- Added `initial_context(analysis_id, input_payload, runtime_payload)`.
- Added `reduce_context(state, draft)` as a pure in-memory transition function.
- Added `canonical_state_hash(state)` using canonical JSON with sorted keys and compact separators, excluding `state_hash`.
- Added explicit transition handling for all declared event types.
- Enforced reducer invariants for:
  - duplicate active turns
  - events targeting unknown or mismatched active turns
  - result revision mismatches against the active baseline
  - duplicate identifiers with different content
  - unknown consumed/reference refs
  - analysis completion while a turn is active
  - model-authored verified facts

## TDD evidence

RED run:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q
ModuleNotFoundError: No module named 'grid_agent.analysis.models'
```

GREEN run:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q
4 passed in 0.06s
```

## Verification

Focused reducer tests pass.

Broader Makefile validation targets were not run because the task request specifically asked to commit and report as soon as Task 2 passes its focused tests.

## Concerns

None for the requested Task 2 scope.

## Repair pass: review requested fixes

Status: DONE

Implemented follow-up reducer corrections requested by review:

- `fact.verified` now requires explicit `authored_by` provenance of `simulator` or `gridctl`; omitted and non-simulator values are rejected.
- `fact.verified` now validates every referenced evidence record exists in `state.evidence` and carries simulator/gridctl provenance through `kind` or `summary.provenance`.
- `result.branches.rank` observations now must consume at least one preexisting result ref and must not produce refs.
- Terminal contexts (`completed` or `failed`) now reject subsequent mutation events, including `analysis.started`, `turn.started`, and diagnostics.
- Completed turn IDs cannot be started again, and completing a duplicate turn ID is rejected defensively.

Added regression tests for:

- omitted `fact.verified` provenance
- unsupported evidence provenance
- ranking observations with produced refs
- ranking observations without a preexisting consumed result ref
- normal mutation attempts after terminal status
- duplicate completed turn IDs

RED evidence:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q
6 failed, 4 passed in 0.09s
```

GREEN evidence:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q
10 passed in 0.06s
```

Concerns: none for the requested correction scope.
