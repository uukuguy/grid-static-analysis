# Native Capture Task 4 Report: Bounded decisions and structured claims

Date: 2026-08-14

Status: implemented, reviewed, and verified

## Scope

Implemented only the approved Task 4 boundary:

- Published and registered `grid_record_decision` for native runs with 1–500
  character fields and at most 20 controller-known current-run refs.
- Added bounded `claims[]` to `grid_submit_answer` without inspecting or parsing
  `answer_output` prose.
- Added immutable Pydantic `AnswerClaim` and `AnswerSubmission` models plus
  `validate_submission`.
- Required every topology, constraint, numerical-result, and risk-judgment claim
  to carry verified current-run result or evidence lineage.
- Required offline-information claims to carry no simulator refs and therefore
  create no run evidence.
- Required claim-ref unions to be declared by the answer-level result/evidence
  arrays.
- Correlated accepted claim events and the terminal answer event with one
  `submission_id`; structural rejection records only a bounded rejection reason
  and emits no claim event.

## Files

- `packages/grid-agent/src/grid_agent/trajectory/answers.py` (new)
- `packages/grid-agent/tests/trajectory/test_answers.py` (new)
- `packages/pi-grid-tools/src/domain-tools.mjs`
- `packages/pi-grid-tools/test/domain-tools.test.mjs`
- `packages/grid-agent/src/grid_agent/analysis/turns.py`
- `packages/grid-agent/tests/analysis/test_turns.py`
- `packages/grid-agent/src/grid_agent/tools/catalog.py`
- `packages/grid-agent/tests/tools/test_catalog.py`

## TDD evidence

### RED

Node contract command:

```sh
npm test --prefix packages/pi-grid-tools -- --test-name-pattern="decision|claims"
```

Observed expected failures:

```text
grid_record_decision was not registered
grid_submit_answer draft had no submission_id or claims
2 failed, 2 passed
```

Python contract command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/trajectory/test_answers.py \
  packages/grid-agent/tests/analysis/test_turns.py \
  packages/grid-agent/tests/tools/test_catalog.py -q
```

Observed expected collection failure:

```text
ModuleNotFoundError: No module named 'grid_agent.trajectory.answers'
```

### GREEN

Focused Task 4 checks after implementation and review fix:

```text
Python Task 4: 29 passed
Node decision/claims: 4 passed
```

Broader affected checks:

```text
Node package: 24 passed
Python runner/turn/claim/catalog: 43 passed
Python trajectory/turn/catalog: 130 passed
```

Full grid-agent regression:

```text
390 passed in 64.65s
```

Static verification:

```text
node --check packages/pi-grid-tools/src/domain-tools.mjs: passed
Ruff on changed Python files: passed
Pyright on changed Python files: 0 errors, 0 warnings
mypy on changed production Python files: no issues
git diff --check: passed
```

## Acceptance semantics

- Decision execution rereads `trajectory-allowed-refs.json`; unknown refs and
  malformed/out-of-bounds declarations return typed tool errors.
- Claim validation operates only on structured claim fields. Answer prose is an
  opaque public string and is never mined for facts, refs, or reasoning.
- Simulator-backed claim refs must be controller-known, answer-declared, and
  accepted by `ContentReferenceVerifier` before any claim event is appended.
- The answer artifact is persisted before claims. Accepted claim events are
  appended immediately before the bridge emits the correlated
  `answer.submitted` event.
- A rejected structured submission emits `answer.rejected` with only
  `error_type` and a bounded generic message; proposed statements and refs are
  not persisted as claim events.
- A recorder/bridge failure between claim events and `answer.submitted` leaves
  an explicitly dangling submission. It is not accepted because no terminal
  answer event with the same `submission_id` exists; this approved crash
  behavior has a regression test.
- `AnswerDraftError` is in the runner's existing fail-closed integrity exception
  family, so a rejected live submission cannot escape normal analysis failure
  cleanup.

## Review

The mandatory read-only review initially identified runner exception integration,
dangling-submission semantics, and Task 5 composition. The runner integration was
fixed and reverified. The reviewer then confirmed that dangling submissions match
approved design §7.4 and that CLI/native composition belongs to Task 5.

Final review result: no Critical, Important, or Minor findings; approved for Task
4 scope.

## Boundary review and follow-up

- No shell, generic file access, raw pandapower object, arbitrary Python, hidden
  reasoning field, or legacy query capability was exposed.
- Decision declarations remain agent intent and cannot create simulator truth,
  results, facts, or evidence.
- Existing stdout-envelope and answer-output semantics remain unchanged.
- The unrelated pre-existing edits in `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` were not staged or modified by Task 4.
- Task 5 still owns live CLI construction of the artifact registry, recorder,
  bridge, capture adapter, native runtime paths, allowed-ref state, and passing
  the shared recorder into `TurnController`.
