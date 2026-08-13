# Task 3 Report: Durable ledger, replay, and normative schemas

## Summary

Implemented `AnalysisContextStore` as a durable persistence boundary for analysis context state. The store initializes a deterministic revision-zero genesis state, commits the first `analysis.started` event as sequence/revision 1, appends every subsequent event to JSONL with fsync before replacing the snapshot atomically, and can replay the ledger into an identical `AnalysisContext`.

Generated normative JSON schemas for `AnalysisContext` and `AnalysisContextEvent`, with a contract test that ensures checked-in schemas stay synchronized with the Pydantic models.

## Files changed

- Created `packages/grid-agent/src/grid_agent/analysis/store.py`
- Created `packages/grid-agent/tests/analysis/test_store.py`
- Created `scripts/update_analysis_context_schemas.py`
- Created `schemas/analysis-context-v1.schema.json`
- Created `schemas/analysis-context-event-v1.schema.json`
- Created `packages/grid-agent/tests/contract/test_analysis_context_docs.py`

## Behavior covered

- `AnalysisContextStore.initialize(workspace, input_record=..., runtime_record=...)`
  - Builds deterministic revision-zero `initializing` state with `initial_context`.
  - Appends `analysis.started` with complete input/runtime payload as sequence 1 / revision 1.
  - Materializes the running snapshot only after ledger fsync.

- `AnalysisContextStore.append(draft, integrity="verified")`
  - Reduces state through `reduce_context`.
  - Emits an `AnalysisContextEvent` containing contiguous sequence/revision and previous/next state hashes.
  - Fsyncs the ledger append before atomic snapshot replacement.

- `AnalysisContextStore.replay(ledger_path)`
  - Rebuilds genesis from the first `analysis.started` payload.
  - Rejects empty, malformed, truncated, non-contiguous, revision-mismatched, previous-hash-mismatched, and next-hash-mismatched ledgers.

- `AnalysisContextStore.verify_materialized_snapshot()`
  - Validates the materialized snapshot against both the in-memory snapshot and replayed ledger state.

## TDD evidence

RED:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py -q
```

Result: failed during collection because `grid_agent.analysis.store` did not exist.

GREEN / focused:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py -q
```

Result: `7 passed in 0.08s`.

Broader package verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
```

Result: `178 passed in 47.61s`.

Schema generation idempotence:

```sh
uv run --project packages/grid-agent python scripts/update_analysis_context_schemas.py
```

Result: second run preserved the same SHA-256 hashes for both generated schema files.

## Notes and concerns

- No Pi/runtime integration was added.
- Existing unrelated workspace changes were preserved and not staged.
- The report file is local under `.superpowers/sdd/`, which is ignored by that directory's `.gitignore`.

## Review fix evidence: append integrity type

Review finding fixed: `AnalysisContextStore.append()` now declares `integrity` as `Literal["verified", "diagnostic"]`, matching `AnalysisContextEvent.integrity`, while retaining the runtime guard for dynamically typed callers.

RED:

```sh
pyright packages/grid-agent/src/grid_agent/analysis/store.py
```

Result before fix: one `reportArgumentType` error because `str` could not be assigned to `Literal['verified', 'diagnostic']`.

Verification after fix:

```sh
pyright packages/grid-agent/src/grid_agent/analysis/store.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py -q
```

Result: `7 passed in 0.12s`.
