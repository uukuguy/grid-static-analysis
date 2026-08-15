# Native Capture Integration Fix Report

Date: 2026-08-15

Status: implemented and verified

## Scope

Resolved the three Important native-capture whole-branch review findings:

1. Accepted `business.claim.declared` events are now appended only after the
   matching native `answer.submitted` event is durable. Each claim carries the
   answer sequence as its native parent, and an answer append failure emits no
   accepted claim.
2. A successful, identity-matched `grid_record_decision` completion now emits a
   native `business.decision.declared` event. The declaration is bounded,
   restricted to the four public decision fields, checked against the original
   tool arguments and controller-published references, sourced as
   `agent-declared`, and causally linked to its completed tool call.
3. Pi stderr is drained continuously into a bounded buffer. RPC stdout EOF now
   inspects the child return code and capture-fatal marker; exit 86 or the
   marker raises `CaptureIntegrityError` instead of a generic EOF protocol
   error. The Analysis runner records the terminal native failure with
   `error_type=capture_integrity_error`.

## Files

- `packages/grid-agent/src/grid_agent/analysis/turns.py`
- `packages/grid-agent/src/grid_agent/trajectory/capture.py`
- `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- `packages/grid-agent/src/grid_agent/analysis/runner.py`
- `packages/grid-agent/tests/analysis/test_turns.py`
- `packages/grid-agent/tests/trajectory/test_capture.py`
- `packages/grid-agent/tests/runtime/test_rpc.py`
- `packages/grid-agent/tests/analysis/test_runner.py`
- `.superpowers/sdd/native-capture-integration-fix-report.md`

## TDD evidence

### RED

Command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_turns.py \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py \
  packages/grid-agent/tests/analysis/test_runner.py -q
```

Observed the intended missing-behavior failures:

- accepted claim preceded `answer.submitted`;
- answer append failure left a dangling accepted claim;
- successful decision completion emitted no business decision event;
- invalid decision bounds and unknown refs were not rejected;
- exit 86 surfaced as `PiProtocolError: Pi RPC ended before agent completion`;
- native runner terminal failure used generic `analysis_error`.

The first combined RED run also exposed an incorrect non-native runner fixture
in the newly added terminal test. After switching that test to the existing
native harness, its isolated RED failed on the intended assertion:

```text
assert 'analysis_error' == 'capture_integrity_error'
```

### GREEN

Focused command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_turns.py \
  packages/grid-agent/tests/trajectory/test_capture.py \
  packages/grid-agent/tests/runtime/test_rpc.py \
  packages/grid-agent/tests/analysis/test_runner.py -q
```

Observed result:

```text
57 passed in 0.82s
```

After tightening the negative decision test to pass the same invalid values as
both invocation arguments and tool result, the focused capture suite remained
green:

```text
11 passed in 0.26s
```

### Broader verification

Command:

```sh
make test-agent
```

Observed result:

```text
398 passed in 72.63s
```

Repository-wide command:

```sh
make test
```

Observed result:

```text
grid-agent: 398 passed in 72.28s
grid-simulator: 87 passed, 18 existing pandapower deprecation warnings
pi-grid-tools: 24 passed
```

`git diff --check` also completed with no whitespace errors.

## Implementation notes

- `AnalysisContextStore.append(answer.submitted)` returns the compatibility
  event carrying the committed native sequence. Claim emission uses that
  sequence as `causation.parent_sequence`; if no native answer sequence exists,
  no accepted native claim is emitted.
- Decision declarations are emitted only when both the started tool name and
  completed capability are `grid_record_decision` and `ok` is true. Result
  fields must exactly match the invocation arguments, text fields are 1–500
  characters, refs are at most 20 non-empty strings, and every ref must be in
  `context/trajectory-allowed-refs.json`.
- The decision event consumes the declared refs, uses the completed tool event
  as its parent, and uses the tool call ID as its correlation ID. No reasoning
  fields or free-form internal state are persisted.
- The stderr reader retains only the latest 64 KiB while draining the pipe, so
  a verbose child cannot block Pi on a full stderr pipe or cause unbounded
  controller memory growth.

## Boundary review

- The stdout answer envelope is unchanged.
- No shell, file, Python, pandapower, or simulator capability was added to Pi.
- Numerical and network claims still cross only the existing `gridctl`
  capability boundary.
- The Node extension remains a sidecar writer only; Python remains the sole
  native event-log writer.
- Existing unrelated modifications in `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` were not edited or staged.
