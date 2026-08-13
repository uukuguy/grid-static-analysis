# Task 6 Report: Tool-result projector and verified fact promotion

## Summary

Implemented the analysis-context projector for normalized semantic tool events:

- Added `AnalysisContextProjector.observe(event, *, turn_id)` in `grid_agent.analysis.projector`.
- Paired tool starts and tool results by stable `tool_call_id`, preserving actual start arguments for dependency projection.
- Added explicit semantic tool-name/capability mismatch protection for paired successful results.
- Admitted successful simulator artifacts through `ContentReferenceVerifier` before appending verified state.
- Appended deterministic store events for:
  - baseline/context opening,
  - tool observations,
  - result registration,
  - evidence registration,
  - verified fact promotion,
  - diagnostics and limitations for normal tool failures.
- Kept large result bodies in digest-verified artifacts and projected compact summaries/facts only.
- Restricted fact promotion to the explicit allowlist:
  - `topology.branch.endpoints.get`: branch endpoint identity,
  - `analysis.powerflow.ac.run`: convergence and total active loss,
  - `result.branches.rank`: ranked branch metric values and units,
  - `analysis.contingency.n_minus_one.run`: aggregate status, scenario count, maximum scenario loading, and violation count.
- Ensured `result.branches.rank` consumes a prior `result_ref` and produces no new result refs.
- Preserved the integrity distinction:
  - normal tool errors record diagnostic/limitation state,
  - successful but corrupted or mismatched simulator artifacts raise `SimulatorIntegrityError`.

## Files changed

- Created `packages/grid-agent/src/grid_agent/analysis/projector.py`
- Created `packages/grid-agent/tests/analysis/test_projector.py`

Committed as:

```text
0f1e3af feat: project verified grid analysis state
```

## TDD evidence

RED check:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

ERROR packages/grid-agent/tests/analysis/test_projector.py
ModuleNotFoundError: No module named 'grid_agent.analysis.projector'
```

GREEN focused check:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

7 passed in 0.12s
```

Requested Task 6 gate:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py packages/grid-agent/tests/analysis/test_reducer.py packages/grid-agent/tests/analysis/test_integrity.py -q

30 passed in 5.81s
```

Whitespace/diff check:

```text
git diff --check -- packages/grid-agent/src/grid_agent/analysis/projector.py packages/grid-agent/tests/analysis/test_projector.py

exit 0
```

## Test coverage added

`packages/grid-agent/tests/analysis/test_projector.py` covers:

- Power-flow projection plus downstream ranking dependency.
- Ranking observation consumes the previous `result_ref` and produces no refs.
- Ranking fact promotion for branch metric values and units.
- Normal tool failure records unresolved limitation.
- Successful corrupted/missing simulator artifact raises `SimulatorIntegrityError`.
- Context opening baseline projection.
- Topology endpoint evidence and verified endpoint facts.
- N-1 aggregate/scenario fact promotion.
- Duplicate reference deduplication.
- Unknown result fields are ignored and not promoted.
- Start/result context mismatch raises `SimulatorIntegrityError`.
- Active-baseline revision mismatch is surfaced through store/reducer rejection.

## Self-review

- Confirmed the projector does not change runner, CLI, Pi runtime, or RPC behavior.
- Confirmed successful simulator-backed projection crosses the existing `ContentReferenceVerifier` boundary before state promotion.
- Confirmed promoted facts come only from `PROMOTED_FACT_FIELDS`.
- Confirmed `result.branches.rank` does not call artifact admission for a new result and records `produced_refs=[]`.
- Confirmed observations/results/evidence/facts are appended in deterministic order.
- Confirmed duplicate evidence refs are deduplicated before result registration.
- Confirmed the Task 6 commit contains only:
  - `packages/grid-agent/src/grid_agent/analysis/projector.py`
  - `packages/grid-agent/tests/analysis/test_projector.py`

## Concerns

- The current `VerifiedFact` model stores `fact_ref`, `statement`, `evidence_refs`, and `verifier_capability`; it does not expose separate structured fields like `predicate`, `context_ref`, `revision_ref`, or `source_observation_id`.
- To preserve current model/reducer boundaries and avoid Task 6 scope creep, the projector stores promoted fact metadata as deterministic canonical JSON inside `VerifiedFact.statement`.
- Tests assert predicates by parsing that JSON statement. A future model migration could promote those fields into first-class `VerifiedFact` attributes without changing the simulator-verification boundary.

## Worktree notes

- Pre-existing unrelated worktree changes were left untouched.
- `docs/status/JOURNAL.md` was already modified before Task 6 reporting; the required journal line for `0f1e3af` was appended but not committed with the Task 6 code commit to avoid mixing unrelated state-file edits.

## Review repair: verified fact sourcing and projector ordering

Commit: pending at report time.

### Findings fixed

- Stopped promoting allowlisted fact values from inline successful tool results when verified artifacts exist.
  - AC and N-1 fact values now derive from verified result documents.
  - Topology endpoint fact values now derive from verified evidence facts.
  - Inline scalar mismatches against verified fact fields now raise `SimulatorIntegrityError`.
- Added forged-inline regressions for AC total active loss and topology endpoint values.
- Added verified consumed-result context propagation for `result.branches.rank` fact statements.
- Required every successful projector-managed tool result to have a matching start event by call ID.
  - Normal failed tool results still record observation, limitation, and diagnostic state without a start.
- Enforced projector append order:
  - `tool.observation.recorded`
  - `simulator.context.opened`
  - `result.registered`
  - `evidence.registered`
  - `fact.verified`
  - for failures: `tool.observation.recorded`, then `limitation.recorded`, then `tool.failed`
- Adapted reducer observation validation narrowly so observation-first ledgering can record a consumed `context:sha256:*` before the matching baseline event lands in the same successful projection.
  - Turn completion still validates consumed refs after projection.
  - Ranking still requires a preexisting registered result.
- Rewrote `_max_scenario_loading` with an explicitly typed numeric accumulation loop for pyright.

### RED evidence

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

5 failed, 6 passed in 0.20s
```

The failures covered:

- ranking fact missing consumed-result `context_ref`,
- successful result without start did not raise,
- forged inline AC value did not raise,
- topology fact came from inline value instead of verified evidence,
- ledger order emitted artifacts before the observation-first sequence required by review.

### GREEN / verification evidence

Focused projector check:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

11 passed in 0.15s
```

Required analysis gate:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py packages/grid-agent/tests/analysis/test_reducer.py packages/grid-agent/tests/analysis/test_integrity.py -q

34 passed in 5.86s
```

Changed-file pyright:

```text
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/analysis/projector.py packages/grid-agent/src/grid_agent/analysis/reducer.py packages/grid-agent/tests/analysis/test_projector.py

0 errors, 0 warnings, 0 informations
```

## Review repair: failed ranking dependency diagnostics

Commit: pending at report time.

### Finding fixed

- Failed tool results now record observation, limitation, and diagnostic state without enforcing successful dependency existence.
- This specifically covers failed `result.branches.rank` calls with unknown or bad `result_ref` values.
- The failed observation keeps `consumed_refs=[]` so reducer dependency validation is not triggered for an unsuccessful tool.
- Original failed args remain available for diagnosis in:
  - `ObservationRecord.producer_observation["args"]`
  - `DiagnosticRecord.details["args"]`
- Reducer ranking dependency validation remains active unless the observation explicitly has `summary.ok is False`.

### RED evidence

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

1 failed, 11 passed in 0.21s
```

The regression failed because a failed ranking result with an unknown `result_ref` still raised before recording limitation state.

### GREEN / verification evidence

Focused projector check:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q

12 passed in 0.17s
```

Required analysis gate:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py packages/grid-agent/tests/analysis/test_reducer.py packages/grid-agent/tests/analysis/test_integrity.py -q

35 passed in 5.91s
```

Changed-file pyright:

```text
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/analysis/projector.py packages/grid-agent/src/grid_agent/analysis/reducer.py packages/grid-agent/tests/analysis/test_projector.py

0 errors, 0 warnings, 0 informations
```
