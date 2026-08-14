# Task 1 Report: Canonical JSON and typed event envelope

Date: 2026-08-14

Status: implemented and verified

## Scope

Implemented only the Task 1 trajectory protocol surface. Existing runtime behavior,
stdout envelopes, simulator boundaries, and existing analysis workspace behavior were
not changed.

## Files changed

- `packages/grid-agent/src/grid_agent/trajectory/__init__.py`
- `packages/grid-agent/src/grid_agent/trajectory/canonical.py`
- `packages/grid-agent/src/grid_agent/trajectory/events.py`
- `packages/grid-agent/tests/trajectory/__init__.py`
- `packages/grid-agent/tests/trajectory/test_events.py`

## TDD evidence

### RED

Command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q
```

Observed output:

```text
ImportError while importing test module 'packages/grid-agent/tests/trajectory/test_events.py'.
ModuleNotFoundError: No module named 'grid_agent.trajectory'
1 error in 0.07s
```

This was the expected failure before the new package existed.

### GREEN

Command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q
```

Observed output:

```text
..........                                                               [100%]
10 passed in 0.06s
```

Also run:

```sh
git diff --check
```

Observed result: success with no whitespace errors.

## Implementation

- Added deterministic UTF-8 canonical JSON with sorted keys, compact separators,
  final newline, non-finite-number rejection, and SHA-256 reference formatting.
- Added immutable, extra-forbidden envelope models for scope, causation, provenance,
  context boundaries, references, drafts, and persisted events.
- Enforced `turn -> step -> request -> tool call` scope nesting.
- Added the complete closed `PAYLOAD_MODELS` vocabulary and normalized every draft
  payload through its event-specific Pydantic model before use.
- Added native `grid-run-event/1.0` event construction, UTC microsecond timestamps,
  SHA-256 field validation, and canonical pre-hash event construction.

## Self-review

- Confirmed `PAYLOAD_MODELS` includes all 25 required event types and rejects extra
  payload fields through `StrictFrozenModel`.
- Confirmed source kinds are limited to persisted `observed` and `agent-declared`;
  `derived` remains a projection-only concept.
- Confirmed the hash is formed only from the complete envelope prior to adding
  `event_hash`, then the final envelope is validated and canonical round-trips.
- Confirmed no later recorder, reader, artifact, workspace, model-capability, or
  runtime integration code was added.

## Concerns

None. The future recorder task remains responsible for durable append/fsync,
registered-reference admission, prohibited-content rejection, and fail-closed replay.

## Review follow-up fix: event timestamp and predecessor seed validation

Addressed the Task 1 review findings within the event envelope only.

### RED

After adding regression coverage, ran:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q
```

Observed result:

```text
..........FFFFF                                                          [100%]
5 failed, 10 passed in 0.08s
```

The failures were the intended gaps: a naive `datetime` was accepted, two
calendar-invalid timestamp strings passed the regex, and both invalid
zero-predecessor boundaries were accepted.

### GREEN

Ran:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py -q
git diff --check
```

Observed result:

```text
...............                                                          [100%]
15 passed in 0.06s
```

`git diff --check` completed successfully with no whitespace errors.

### Changed files

- `packages/grid-agent/src/grid_agent/trajectory/events.py`
- `packages/grid-agent/tests/trajectory/test_events.py`

### Implementation and self-review

- `build_event` now rejects datetimes without a UTC offset before conversion.
- `RunEvent` semantically parses its regex-conforming timestamp and requires the
  exact six-digit UTC `Z` form.
- The all-zero predecessor hash is required for sequence 1 and forbidden for later
  sequences. No cross-event sequence-contiguity rule was added; that remains
  recorder-owned.
- Regression tests cover naive input, malformed-but-regex-matching date/time values,
  and both predecessor-seed boundaries.

### Concerns

None. This change intentionally does not determine whether a nonzero predecessor
hash is the actual prior event; durable chain contiguity belongs to the recorder.
