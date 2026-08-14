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
