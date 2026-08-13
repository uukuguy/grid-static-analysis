# Task 8 Report: Turn isolation, archival, and incremental answers

## Summary

Implemented Task 8.

- Added `grid_agent.analysis.turns` with:
  - `ActiveTurnHandle`
  - `FinalizedTurn`
  - `TurnController.start(...)`
  - `TurnController.finalize(...)`
  - `TurnController.fail(...)`
  - `AnswerDraftError` and `StaleAnswerDraftError`
- Added nonce-bound turn starts that:
  - generate `secrets.token_urlsafe(32)` nonces,
  - write raw nonces only to `active-turn.json` and bound answer drafts,
  - record only `nonce_sha256` in `AnalysisContext`,
  - clear stale active drafts before each prompt.
- Added finalization behavior that:
  - rejects stale drafts without completing the active turn,
  - archives current bound drafts under `turns/<ordinal>/answer-draft.json`,
  - writes accepted answer envelopes to `turns/<ordinal>/answer.json`,
  - appends incremental answer envelopes to `output/answers.jsonl` with flush/fsync,
  - preserves `answer_output` unchanged across draft, answer JSON, and JSONL.
- Added non-blocking audit support that archives diagnostics to `answer-audit.json` and records context diagnostics without mutating accepted answers.
- Added missing-draft handling that completes a failed turn, records an unresolved limitation, and emits an incremental limitation answer instead of accepting stale output.

## TDD evidence

RED:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: failed during collection with `ModuleNotFoundError: No module named 'grid_agent.analysis.turns'`, matching the missing Task 8 interface.

GREEN focused verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: `5 passed`.

Required verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/cli/test_app.py -q
```

Result: `21 passed`.

## Notes

- Runner and CLI wiring were intentionally not changed.
- Existing unrelated working-tree changes were left untouched.

## High finding fixes

Follow-up commit fixes both Task 8 high findings.

- `finalize(...)` now converts structural current-draft errors into failed turns with limitations and incremental JSONL answers:
  - invalid JSON,
  - non-object JSON,
  - missing `answer_output`,
  - malformed `claim_evidence_refs`,
  - malformed `result_refs`.
- Stale turn binding still raises `StaleAnswerDraftError` and does not complete the active turn.
- `start(...)` now preflights that the context store has no active turn before touching active prompt files.
- `start(...)` now preserves the previous active record and draft when the context store rejects `turn.started`.

Follow-up RED:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: `7 failed, 5 passed`, covering malformed drafts and start rollback/preservation regressions.

Follow-up GREEN:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: `12 passed`.

Follow-up required verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/cli/test_app.py -q
```

Result: `28 passed`.

Pyright:

```sh
PYTHONPATH=packages/grid-agent/src pyright packages/grid-agent/src/grid_agent/analysis/turns.py packages/grid-agent/tests/analysis/test_turns.py
```

Result: `0 errors, 0 warnings, 0 informations`.

## Final atomicity high finding fix

Final follow-up commit fixes the remaining `start(...)` activation atomicity finding.

- `start(...)` now snapshots prior `active-turn.json` and `answer-draft.json` bytes.
- It performs filesystem activation first by clearing the active draft and writing the new active turn record.
- Only after filesystem activation succeeds does it append `turn.started` to `AnalysisContext`.
- If filesystem activation fails, the prior active files are restored and the context is not mutated.
- If context append fails, the prior active files are restored.

Final RED:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: `1 failed, 12 passed`; simulated active-record write failure deleted the prior draft.

Final focused verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q
```

Result: `13 passed`.

Final required verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/cli/test_app.py -q
```

Result: `29 passed`.

Final pyright:

```sh
PYTHONPATH=packages/grid-agent/src pyright packages/grid-agent/src/grid_agent/analysis/turns.py packages/grid-agent/tests/analysis/test_turns.py
```

Result: `0 errors, 0 warnings, 0 informations`.
