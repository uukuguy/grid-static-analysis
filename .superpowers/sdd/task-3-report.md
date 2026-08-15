# Task 3 Report: Immutable sidecar registry

## Implementation

- Added `ArtifactPointer` and `ImmutableArtifactRegistry` for the three declared
  trajectory sidecar layouts.
- JSON writes are canonical, fsynced to a temporary file, atomically published
  without replacing an existing path, directory-fsynced, and digest-verified
  before a pointer is returned.
- Existing artifacts are admitted byte-for-byte without rewriting.  All
  admission and verification paths reject invalid identities, mismatched
  registered paths, symlinks, non-regular files, out-of-root paths, and changed
  size or digest.

## TDD evidence

### RED

1. `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py -q`
   - Failed in collection as expected: `ModuleNotFoundError: No module named
     'grid_agent.trajectory.artifacts'`.
2. `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_run_root_beneath_a_symlink -q`
   - Failed as expected because a registry accepted a root below a symlinked
     ancestor.
3. `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_non_string_kind_and_identity -q`
   - Failed as expected because a non-string identity raised `TypeError` rather
     than `ArtifactIntegrityError`.

### GREEN / verification

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py -q`
  - `12 passed in 0.07s`.
- `uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/artifacts.py packages/grid-agent/tests/trajectory/test_artifacts.py`
  - `All checks passed!`
- `uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
  - Completed successfully.
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q`
  - `67 passed in 0.14s`.

## Files changed

- `packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
- `packages/grid-agent/tests/trajectory/test_artifacts.py`

## Self-review

- Confirmed pointers encode the digest, relative path, kind, and byte size and
  that verification independently recomputes both size and SHA-256.
- Confirmed idempotent same-byte writes and exact-byte pre-existing artifact
  admission; a content mismatch fails closed.
- Confirmed the supplied registration path must exactly equal the layout path.
- Confirmed every existing path component beneath the real run root is checked
  with `lstat`, and both a symlinked request directory and a symlinked run-root
  ancestor are rejected.

## Concerns

No known concerns within this task's owned scope.

## Review fix: descriptor-rooted TOCTOU protection

### Finding addressed

The original registry checked directories and files with `lstat()` and then
read or published through pathnames.  A directory or artifact could therefore
be replaced with a symlink after the check, causing matching bytes from outside
the run root to be verified.

All artifact operations now traverse the absolute run-root prefix and every
artifact-relative directory component through directory descriptors using
`O_NOFOLLOW`.  Artifact bytes are read only from an `O_NOFOLLOW` descriptor
whose type is checked with `fstat()`.  Atomic writes create, fsync, hard-link,
and unlink the temporary file relative to the already verified parent
descriptor.  Before `verify()` returns its required `Path`, it reopens the
named root, parent, and artifact without following symlinks and compares their
device/inode identities with the descriptors used for the verified read.

### TDD evidence

RED, before the implementation change:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_replacement_during_verified_read -q
```

Result: `2 failed in 0.09s`.  Both the parent replacement and final-file
replacement cases failed with `DID NOT RAISE ArtifactIntegrityError`, proving
that an outside regular file with matching bytes passed the old pathname-based
verification.

GREEN, after the descriptor-rooted implementation:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py::test_registry_rejects_replacement_during_verified_read -q
```

Result: `2 passed in 0.07s`.

Focused artifact suite:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_artifacts.py -q
```

Result: `14 passed in 0.09s`.

Broader trajectory suite:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q
```

Result: `69 passed in 0.15s`.

Static checks:

```sh
uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/artifacts.py packages/grid-agent/tests/trajectory/test_artifacts.py
uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/trajectory/artifacts.py
pyright packages/grid-agent/src/grid_agent/trajectory/artifacts.py
git diff --check
```

Results: Ruff reported `All checks passed!`; compileall and `git diff --check`
completed successfully; Pyright reported `0 errors, 0 warnings, 0
informations` for the production module.  A combined source/test Pyright
invocation was also attempted, but this repository's standalone Pyright
configuration does not resolve the package import from the test file; the
production-module invocation above is clean.

### Review-fix files

- `packages/grid-agent/src/grid_agent/trajectory/artifacts.py`
- `packages/grid-agent/tests/trajectory/test_artifacts.py`

No event, recorder, or workspace files were changed by this review fix.
