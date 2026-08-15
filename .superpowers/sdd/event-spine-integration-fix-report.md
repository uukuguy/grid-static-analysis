# Event Spine Integration Fix Report

Date: 2026-08-14

Status: implemented and verified

## Scope

Resolved the three Important findings from the whole-branch Event Spine review:

1. Enforced artifact-before-event admission in `RunEventRecorder`.
2. Added immutable current-run registration for result, evidence, and tool-result
   sidecars using the repository's existing workspace layouts.
3. Made every top-level persisted `RunEvent` envelope member required in both
   Pydantic validation and the checked-in JSON Schema.

Existing runtime capture behavior was not wired to the native spine in this fix.
The existing context ledger, semantic trace, stdout contract, and simulator
formats remain unchanged.

## TDD Evidence

### Finding 1: artifact-before-event admission

RED command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_rejects_unregistered_artifact_references packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_accepts_registered_digest_verified_artifact_pointer -q
```

Observed result before production changes:

```text
FFF
3 failed in 0.31s
TypeError: RunEventRecorder.__init__() got an unexpected keyword argument 'artifact_registry'
```

GREEN coverage now proves that:

- a fake reference in either `payload.artifact_ref` or `EventRefs` is rejected
  before the event file is created;
- an `ArtifactPointer.ref` returned by the same immutable registry is accepted;
- the registry reverifies the exact bytes, size, digest, path binding, and no-follow
  descriptor chain immediately before append;
- recorder construction and append remain valid for events with no artifact refs.

### Finding 2: current-run result/evidence/tool-result admission

RED command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_registers_current_run_artifact_kinds_without_rewriting packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_new_artifact_kinds_outside_registered_layout packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_symlinked_new_artifact_kind_directories -q
```

Observed result before production changes:

```text
FFFFFFFFF
9 failed in 0.15s
ArtifactIntegrityError: artifact kind is not registered
```

GREEN coverage now proves exact-byte registration plus traversal/layout and
symlink rejection for each new kind. The admitted paths match existing codebase
conventions:

- results: `evidence/results/{powerflow|contingency|contingency-scenario}-<digest>.json`;
- evidence: `evidence/network-facts/network-fact-<digest>.json` and
  `evidence/analysis/analysis-evidence-<digest>.json`;
- tool results: `tool-results/<turn_id>/<tool_call_id>.json`.

These existing artifacts are registration-only: the registry reads their exact
bytes and never rewrites or canonicalizes them. Descriptor-rooted `O_NOFOLLOW`
verification and named-binding checks are shared with the original artifact
kinds.

### Finding 3: complete persisted envelope requirements

RED command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py::test_trajectory_schema_requires_every_persisted_envelope_member -q
```

Observed result before production changes:

```text
F
1 failed in 0.08s
```

The schema required only `event_type`, `analysis_id`, `sequence`, `timestamp`,
`previous_event_hash`, and `event_hash`; seven persisted properties remained
optional.

GREEN behavior now keeps `EventDraft` defaults while defining `RunEvent` as a
separate strict persisted model. All thirteen top-level properties are required:

```text
event_type, scope, causation, source, context, refs, payload, schema_version,
analysis_id, sequence, timestamp, previous_event_hash, event_hash
```

Both draft and persisted models continue to normalize through the same closed
event-specific payload validator.

## Implementation Details

- `ImmutableArtifactRegistry` records only pointers it has produced through an
  atomic write or exact-byte existing-file registration.
- `verify_reference()` rejects references not registered by that registry
  instance and reverifies registered pointers on every admission request.
- `RunEventRecorder` accepts an explicit optional `artifact_registry`
  dependency. It finds payload artifact-reference fields recursively and generic
  artifact references in `refs.consumed`, `refs.produced`, and `refs.evidence`.
- Reference-bearing appends fail before event construction or I/O when registry
  admission fails. Reference-free events do not require a registry.
- The normative schema was regenerated equivalently and now has no default for
  `schema_version`; its `required` set equals its complete property set.

## Files Changed

- `packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
- `packages/grid-agent/src/grid_agent/trajectory/events.py`
- `packages/grid-agent/src/grid_agent/trajectory/recorder.py`
- `packages/grid-agent/tests/trajectory/test_artifacts.py`
- `packages/grid-agent/tests/trajectory/test_events.py`
- `packages/grid-agent/tests/trajectory/test_recorder.py`
- `packages/grid-agent/tests/analysis/test_workspace.py`
- `schemas/grid-run-event-v1.schema.json`
- `.superpowers/sdd/event-spine-integration-fix-report.md`

## Verification

- Focused trajectory/workspace/docs gate:
  `89 passed in 0.20s`.
- Full grid-agent suite (`make test-agent`):
  `351 passed in 63.05s`.
- Ruff over changed trajectory and test surfaces:
  `All checks passed!`.
- Pyright over changed production modules:
  `0 errors, 0 warnings, 0 informations`.
- Production-module compileall: completed successfully.
- Checked-in schema equality and complete-required-members tests: passed as part
  of both focused and full gates.
- `git diff --check`: completed successfully.

## Concerns

No known correctness concerns. The registry's admission memory is intentionally
process-local: a reconstructed registry must explicitly re-register an existing
current-run artifact before a new recorder can cite it. This preserves the
artifact-before-event ordering guarantee rather than trusting discovery by path.

## Commit

Atomic commit subject: `fix: enforce trajectory artifact admission`

## Review Follow-up: Claim and Answer Array Reference Admission

Date: 2026-08-14

### Finding

The original recorder admission walk checked `artifact_ref` values but did not
inspect the `result_refs` and `evidence_refs` arrays on
`business.claim.declared` and `answer.submitted`. An unregistered
`artifact:sha256:...` value in any of those four payload locations could
therefore be appended to the event log.

### Design

Only entries beginning with `artifact:` in those two arrays are sidecar
pointers and must pass the existing process-local immutable-registry admission
check. Existing semantic `result:sha256:...` and `evidence:sha256:...`
references remain outside this sidecar-pointer check, so reference-free events
and existing non-artifact result/evidence references retain their behavior.

### TDD Evidence

RED command (after adding the regression tests and before changing recorder
production code):

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_rejects_unregistered_artifact_claim_and_answer_references packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_accepts_registered_artifact_claim_and_answer_references -q
```

Observed output:

```text
FFFF....                                                                 [100%]
4 failed, 4 passed in 0.15s
```

Each failure was the intended missing-admission symptom:

```text
Failed: DID NOT RAISE RecorderIntegrityError
```

The four failing parametrizations covered unregistered `artifact:sha256:...`
entries in each of:

- `business.claim.declared.result_refs`
- `business.claim.declared.evidence_refs`
- `answer.submitted.result_refs`
- `answer.submitted.evidence_refs`

The four green parametrizations registered an exact-byte current-run result or
evidence sidecar via `ImmutableArtifactRegistry.register_existing(...)`, placed
its returned `ArtifactPointer.ref` in the corresponding array, and appended the
event successfully. `answer.submitted` additionally used a separately
registered answer artifact, isolating the array-under-test.

GREEN command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py -q
```

Observed output:

```text
.......................                                                  [100%]
23 passed in 0.14s
```

Additional focused verification:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q
uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/recorder.py packages/grid-agent/tests/trajectory/test_recorder.py
git diff --check
```

Observed output:

```text
89 passed in 0.38s
All checks passed!
git diff --check exited 0
```

### Implementation

`RunEventRecorder._payload_artifact_references()` now collects only
`artifact:`-prefixed string members of `result_refs` and `evidence_refs`, then
uses the same `ImmutableArtifactRegistry.verify_reference()` path already used
for direct payload and `EventRefs` artifact pointers. Admission still happens
before event construction and opening the event log for append.

### Scope

Changed only:

- `packages/grid-agent/src/grid_agent/trajectory/recorder.py`
- `packages/grid-agent/tests/trajectory/test_recorder.py`
- `.superpowers/sdd/event-spine-integration-fix-report.md`

### Concerns

None known. This is deliberately limited to artifact pointers; validating the
separate semantic result/evidence reference protocol belongs to its existing
current-run verification boundary rather than the trajectory artifact registry.

## Review Follow-up: Directory-entry Durability

Date: 2026-08-14

### Finding

The recorder fsynced appended event bytes before subscriber publication, but a
first append that created `events/run-events.jsonl` did not fsync the containing
directory. The artifact registry fsynced its atomically published artifact name,
but opened each newly created directory before fsyncing that directory's parent.
In either case, a crash could lose a namespace entry whose contents had otherwise
been treated as durable.

### TDD Evidence

RED command (after adding the ordering regressions and before production changes):

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_appends_fsyncs_then_publishes packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_fsyncs_each_parent_before_opening_new_nested_directory -q
```

Observed output:

```text
FF                                                                       [100%]
2 failed in 0.13s
```

The recorder trace omitted `fsync:directory` between the first file fsync and
`publish:1`. The nested artifact trace observed `mkdir:<child>` followed directly
by `open-child:<child>` for `run`, `requests`, and `request-1`, with no intervening
parent fsync.

GREEN command:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_recorder.py::test_recorder_appends_fsyncs_then_publishes packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_fsyncs_each_parent_before_opening_new_nested_directory -q
```

Observed output:

```text
..                                                                       [100%]
2 passed in 0.09s
```

The deterministic traces now require:

- first log append: file fsync, parent-directory fsync, subscriber publication;
- later log append: file fsync, subscriber publication, with no redundant entry sync;
- every registry-created directory: mkdir, parent-descriptor fsync, no-follow child open.

### Implementation

`RunEventRecorder` remembers whether its event path was absent when ownership was
claimed. After the first successful file fsync, it opens and fsyncs the parent
directory before advancing sequence state or invoking subscribers. Any open or
fsync failure follows the existing fail-closed recorder path.

`ImmutableArtifactRegistry._open_child_directory()` now fsyncs the already-open
parent descriptor after a successful descriptor-relative `mkdir` and before its
descriptor-relative `O_DIRECTORY | O_NOFOLLOW` open of the child. Atomic artifact
publication and descriptor-rooted no-follow verification are unchanged.

### Verification

```text
recorder + artifact suites: 47 passed in 0.19s
complete trajectory suite: 90 passed in 0.19s
ruff over changed production/tests: All checks passed!
git diff --check: exited 0
```

### Scope

Changed only:

- `packages/grid-agent/src/grid_agent/trajectory/recorder.py`
- `packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
- `packages/grid-agent/tests/trajectory/test_recorder.py`
- `packages/grid-agent/tests/trajectory/test_artifacts.py`
- `.superpowers/sdd/event-spine-integration-fix-report.md`

### Concerns

None known. Existing empty event logs are treated as pre-existing namespace
entries; the additional parent-directory fsync is performed only when this
recorder's first append creates the log entry.
