# Task 2 Report: Single durable recorder and fail-closed reader

## Status

Completed in commit `aee1661` (`feat: persist and replay trajectory spine`).

## Scope and files changed

- `packages/grid-agent/src/grid_agent/trajectory/recorder.py`
  - Adds `RunEventRecorder`, `RecorderIntegrityError`, durable append/fsync, best-effort subscribers, prohibited-content rejection, and permanent closure after write failure.
- `packages/grid-agent/src/grid_agent/trajectory/reader.py`
  - Adds `RunEventReader`, `ReplayPrefix`, `ReplayFailure`, canonical event-hash recomputation, and first-invalid-line fail-closed replay.
- `packages/grid-agent/tests/trajectory/test_recorder.py`
  - Covers fsync-before-publish ordering, subscriber isolation, prohibited secret/reasoning content, short writes, and fsync failure closure.
- `packages/grid-agent/tests/trajectory/test_reader.py`
  - Covers trusted prefix replay plus malformed JSON, blank lines, unknown event types, invalid envelopes/scopes, sequence gaps, predecessor mismatches, and event-hash mismatches.

No earlier envelope files, runtime wiring, artifact/workspace files, stdout behavior, or simulator behavior changed.

## TDD evidence

### RED

Tests were added before either production module existed.

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q
```

Result: collection failed as expected with `ModuleNotFoundError: No module named 'grid_agent.trajectory.reader'` for both new test modules.

An additional reader classification test then failed as expected because a missing `event_type` was initially treated as `unknown_event` instead of `invalid_event`.

### GREEN

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q
```

Result: `14 passed in 0.08s`.

## Verification

```text
uv run --project . ruff check src/grid_agent/trajectory/recorder.py src/grid_agent/trajectory/reader.py tests/trajectory/test_recorder.py tests/trajectory/test_reader.py
```

Result: `All checks passed!`

```text
uv run --project . pytest tests/trajectory -q
```

Result: `29 passed in 0.09s`.

`git diff --check` also passed before commit.

## Self-review

- The recorder serializes and fsyncs the complete canonical JSONL record before it changes chain state or invokes subscribers.
- Any `OSError` from directory/open/write/flush/fsync closes the recorder permanently; a short write is converted to `OSError` and follows the same path.
- Content rejection occurs before parent-directory creation or append, so prohibited secrets and hidden reasoning are never redacted or silently persisted.
- Reader parsing distinguishes malformed JSON from schema validation, identifies unknown string event types, validates envelopes including scopes, then validates ordering and both hashes before extending the trusted tuple.
- The reader returns only the prefix preceding the first invalid line.

## Concerns

None within Task 2 scope. The recorder deliberately does not resume an existing file; it is the single writer for a fresh run path, while recovery/import behavior belongs to later tasks.

## Review-fix pass: ownership, content filtering, and raw replay trust

Status: completed in commit `20038b7` (`fix: harden trajectory recording and replay`).

### Fixes

- Replaced substring-based prohibited-key matching with exact normalized credential and hidden-reasoning field names. Registered secret values and hidden-reasoning text are still rejected before the event file is created, while ordinary `input_tokens` and `output_tokens` usage fields now append normally.
- Added a per-recorder mutex for append serialization and a nonblocking advisory sidecar lock for sole ownership of one `events_path`. A competing recorder and a pre-existing nonempty log are rejected; close and durability failure release ownership.
- Made replay parsing reject `Infinity`, `-Infinity`, and `NaN` as malformed JSON. Hash recomputation now uses the decoded raw envelope instead of Pydantic-normalized data.
- Required every native envelope member to be present before model validation and hash recomputation, including `scope`, `causation`, `source`, `context`, and `refs`.

### Fresh TDD evidence

RED, after adding the regressions and before production changes:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q
14 failed, 23 passed in 0.17s
```

The failures directly exposed normal usage-field rejection, duplicate concurrent sequence numbers, absent ownership/pre-existing-log checks, permissive non-finite constants, and trusted defaulted envelope members.

GREEN, focused:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q
37 passed in 0.13s
```

GREEN, full trajectory package plus lint:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q
52 passed in 0.13s

uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/recorder.py packages/grid-agent/src/grid_agent/trajectory/reader.py packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py
All checks passed!
```

`git diff --check` also passed before commit.

### Self-review and concerns

- Correction to the earlier self-review: ownership now creates the parent directory and sidecar at construction, but prohibited content is still rejected before the event log itself is created or appended.
- Append validation, event construction, durable write, chain-state advancement, and subscriber publication are serialized as one operation.
- Ownership is released idempotently on close and immediately after a write/fsync failure; tests prove a replacement recorder can acquire the path after cleanup.
- The intentionally minimal recovery behavior rejects every pre-existing nonempty log. Later recovery/import work must not silently change that policy.
- The sidecar lock uses POSIX `fcntl` advisory locking and remains as an empty coordination file after close; the held file descriptor, not sidecar existence, represents ownership.

## Strict replay fix: coercion and numeric overflow

Status: completed in the strict replay fix commit.

### Root cause and fixes

- Pydantic validation accepted JSON values that required coercion, including a string `sequence` and a string numeric payload. Because the reader verified the hash over the decoded raw envelope but returned the normalized typed model, a correctly raw-hashed non-native event could enter the trusted prefix.
- The reader now compares the decoded JSON tree with the validated event's JSON-mode dump using exact recursive type-and-value matching. Any coercion or default insertion fails as `invalid_event` before sequence, predecessor, or event-hash trust.
- Python's JSON decoder turns an overflowing numeric literal such as `1e999` into a non-finite float. The reader now rejects decoded non-finite floats recursively as `invalid_event`, so canonical hash serialization cannot leak `ValueError` and the preceding valid prefix is preserved.

### TDD evidence

RED, after adding the three regressions and before changing `reader.py`:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_reader.py -q
3 failed, 25 passed in 0.14s
```

The two raw-hash tests showed the coerced events incorrectly entering the trusted prefix. The overflow test raised `ValueError: Out of range float values are not JSON compliant: inf` from canonical hash serialization after two valid events.

GREEN, reader regressions:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_reader.py -q
28 passed in 0.10s
```

GREEN, required focused reader/recorder suite plus lint:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_reader.py -q
40 passed in 0.13s

uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/reader.py packages/grid-agent/tests/trajectory/test_reader.py
All checks passed!
```

`git diff --check` also passed.

### Self-review and concerns

- Exact recursive matching distinguishes JSON booleans, integers, floats, and strings even where Python scalar equality would otherwise equate values such as `true` and `1`.
- Non-finite detection covers every decoded list or object position, not only declared numeric model fields.
- No recorder behavior, event schema, or simulator boundary changed.
- No remaining concerns within the requested reader scope.
