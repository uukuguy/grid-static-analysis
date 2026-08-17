# Task 3 Report: Reproducible Tamper-Evident Pi Runtime Patch Install

## Scope

Implemented the installer/lock distribution slice only:

- Upgraded `configs/runtime/pi-runtime.lock.json` to schema version 2.
- Recorded exact `pi_ai_version` (`0.80.6`) and the required patch declaration.
- Added lock-time patch path and byte validation.
- Added deterministic ordered patch identity digest.
- Applied verified patches after detached checkout and before `npm ci`.
- Recorded patch digest identity in the active marker and `PiRuntimeIdentity`.
- Added retry safety for failed installs by resetting and cleaning the managed source before patching.

No `var/` data was modified or migrated.

## Digests

- Patch: `configs/runtime/patches/pi-0.80.6-before-model-request.patch`
- Patch SHA-256: `458794796163d70c71846a4f38a543bf2ed495547c5fd216b2f1e0d684e1da0e`
- Lock SHA-256 after schema v2 update: `42ac45d642541df1e89d7840dc91399b64a981adca752de581f977f3dafca8b7`
- Ordered patch identity SHA-256: `f5127db4b2bd3856a9f12adc7e8499f5c2d6780419e85705c550f2e1244370ad`

## RED Evidence

Initial focused runtime suite after writing schema v2/patch tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
11 failed, 10 passed in 0.42s
```

Representative failures:

- `PiRuntimeLock` had no `pi_ai_version`, `patches`, or `patches_sha256`.
- Schema v2 temp locks were rejected as unsupported schema version.
- Installer never invoked `git apply`.
- Failed patch application did not raise because patching was absent.
- Locator identity lacked `pi_ai_version` and `patches_sha256`.

Retry/idempotency RED checks added after real install failure:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py::test_installer_uses_detached_pinned_commit -q
1 failed
```

Failures confirmed missing `git reset --hard <commit>` first, then missing `git clean -fd` after a second RED run. These were needed because a failed Pi build left patched tracked files and an untracked patch-created test file in `.grid-agent/runtime/pi/source`.

## GREEN Evidence

Focused runtime tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
21 passed in 0.04s
```

Full grid-agent tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
529 passed, 1 warning in 78.26s
```

Repository Makefile test gate:

```text
make test
529 passed, 1 warning in 74.67s
87 passed, 18 warnings in 36.95s
node --test: 25 pass, 0 fail
```

Additional checks:

```text
uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime
exit 0

git diff --check
exit 0
```

No LSP diagnostics tool was exposed in this session. Compile checks and the full Makefile test gate were used as the available diagnostics/type-safety substitute.

## Install / Doctor Evidence

`make install-pi` verified the installer path through clone/fetch/checkout/reset/clean/patch/`npm ci`, then failed in upstream Pi's build step while fetching `https://models.dev/api.json` from Node:

```text
PiRuntimeInstallerError: Pi runtime command failed (npm run build)
Failed to load models.dev data: TypeError: fetch failed
ConnectTimeoutError: Connect Timeout Error (attempted addresses: 199.59.149.237:443, 2001::a88f:abbd:443, timeout: 10000ms)
```

This was reproduced after the reset/clean fix. `curl -I --connect-timeout 10 --max-time 20 https://models.dev` returned HTTP 200 through the shell proxy, but Node v23.11.0 built-in `fetch()` ignored the proxy environment and timed out. `NODE_USE_ENV_PROXY=1` did not change Node's behavior, and `node --help` exposed no proxy flag.

Active marker safety held:

```text
active missing
```

`make doctor` after the failed install completed:

```text
uv run --project packages/grid-agent grid-agent doctor --json
{"gridctl": ".../packages/grid-simulator/.venv/bin/gridctl", "live_probe": false}
```

## Files Changed

- `configs/runtime/pi-runtime.lock.json`
- `packages/grid-agent/src/grid_agent/runtime/lock.py`
- `packages/grid-agent/src/grid_agent/runtime/installer.py`
- `packages/grid-agent/src/grid_agent/runtime/locator.py`
- `packages/grid-agent/tests/runtime/test_installer.py`
- `packages/grid-agent/tests/runtime/test_locator.py`

## Notes

- Existing dirty files outside this task were left untouched: `.superpowers/sdd/task-1-report.md`, `.superpowers/sdd/task-2-report.md`, and `docs/status/JOURNAL.md`.
- The managed runtime source under `.grid-agent/` is ignored runtime state. It remains without an active marker because the upstream Pi build did not complete.

## Security Review Fix: Active Marker Binding

### Finding

Security review found a HIGH binding failure: `PiRuntimeLocator.resolve()` treated an existing managed CLI as usable without validating the `active` marker written only after a completed install. A partial/failed install could therefore leave residual CLI output and be resolved as a managed runtime.

### Change

- `PiRuntimeLocator.resolve()` now treats managed runtime as available only when the CLI exists and the `active` marker is valid.
- The marker must bind the managed source path, pinned commit, lock SHA-256, and combined patch SHA-256 to the current `PiRuntimeLock`.
- Missing marker means no managed runtime and allows normal PATH fallback.
- Present but malformed/mismatched marker is a hard `PiRuntimeLocatorError`; it does not silently fall back to PATH.
- Managed OAuth helper resolution also requires the same active marker.
- `PiRuntimeInstaller.install()` removes any stale `active` marker before patch verification/source mutation.
- Installer cleanup changed from `git clean -fd` to `git clean -fdx` under `.grid-agent/runtime/pi/source` so ignored build output such as `dist` cannot survive failed retries.

### RED Evidence

Focused runtime tests after adding the security-review cases and before implementation:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
6 failed, 20 passed in 0.39s
```

Failures proved:

- Installer still used `git clean -fd`, not ignored-output cleanup.
- Failed build left a stale `active` marker.
- Managed executable without marker still resolved instead of falling back to PATH.
- Malformed, wrong-source, and wrong-digest markers did not raise.

### GREEN Evidence

Focused runtime tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
26 passed in 0.08s
```

Full grid-agent tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
534 passed, 1 warning in 73.97s
```

Additional checks:

```text
uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime
exit 0

git diff --check
exit 0

rg "breakpoint\\(|pdb\\.set_trace|TODO DEBUG|print\\(" packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -n
exit 1, no matches
```

### Residual

The pre-existing Pi 0.80.6 dependency-audit finding was not addressed in this task. Pins remain unchanged by scope.

## Re-review Fix: Cleanup Containment

### Finding

Re-review found a MEDIUM cleanup-containment failure: the installer could invoke runner-backed git commands, especially `git clean -fdx`, before proving `.grid-agent/runtime/pi/source` was a safe managed directory. A symlinked or escaped source path could make cleanup unsafe.

### Change

- Added source preparation/validation before active marker removal, patch verification, mkdir-sensitive mutation, or any runner command.
- Validation rejects a symlinked `source` path.
- Validation creates normal missing source directories, then confirms the path is a directory.
- Validation checks resolved `source` remains inside the resolved `.grid-agent/runtime/pi` root.
- `git clean -fdx` remains confined to the verified managed source directory.
- On invalid source state, `PiRuntimeInstallerError` is raised, the runner is not called, stale marker content is left untouched, and no outside directory is removed.

### RED Evidence

New containment tests before implementation:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py::test_installer_rejects_symlink_source_before_runner_or_marker_mutation packages/grid-agent/tests/runtime/test_installer.py::test_installer_normal_managed_source_proceeds_after_validation -q
1 failed, 1 passed in 0.18s
```

Failure proved symlinked `source` was accepted and install proceeded instead of raising before runner/marker mutation.

### GREEN Evidence

New tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py::test_installer_rejects_symlink_source_before_runner_or_marker_mutation packages/grid-agent/tests/runtime/test_installer.py::test_installer_normal_managed_source_proceeds_after_validation -q
2 passed in 0.37s
```

Focused runtime tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
28 passed in 0.32s
```

Full grid-agent tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
536 passed, 1 warning in 74.69s
```

Additional checks:

```text
uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime
exit 0

git diff --check
exit 0

rg "breakpoint\\(|pdb\\.set_trace|TODO DEBUG|print\\(" packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -n
exit 1, no matches
```

### Residual

The pinned Pi 0.80.6 dependency-audit finding remains out of scope and was not changed.

## Third Review Fix: Runtime Root Containment

### Finding

Third review found a remaining MEDIUM containment gap: the installer validated containment against `self.pi_runtime_dir.resolve()`, so a symlinked `.grid-agent/runtime/pi` root could redirect the managed runtime root to an outside directory and still become the accepted containment base.

### Change

- Added managed runtime root validation before source validation, marker removal, patch verification, or any runner command.
- Rejects symlinked `.grid-agent/runtime/pi` roots.
- Creates a normal missing runtime root, then verifies it is a non-symlink directory.
- Validates `source` as a child under the already validated, non-symlink runtime root.
- Retains previous leaf `source` symlink protections.
- On symlinked root state, `PiRuntimeInstallerError` is raised, runner is not called, stale outside marker remains unchanged, and outside data remains unchanged.

### RED Evidence

New regression before implementation:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py::test_installer_rejects_symlink_runtime_root_before_runner_or_marker_mutation -q
1 failed in 0.06s
```

Failure proved a symlinked runtime root was accepted and install proceeded.

### GREEN Evidence

New regression:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py::test_installer_rejects_symlink_runtime_root_before_runner_or_marker_mutation -q
1 passed in 0.33s
```

Focused runtime tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -q
29 passed in 0.20s
```

Full grid-agent tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests -q
537 passed, 1 warning in 73.34s
```

Additional checks:

```text
uv run --project packages/grid-agent python -m compileall -q packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime
exit 0

git diff --check
exit 0

rg "breakpoint\\(|pdb\\.set_trace|TODO DEBUG|print\\(" packages/grid-agent/src/grid_agent/runtime packages/grid-agent/tests/runtime/test_installer.py packages/grid-agent/tests/runtime/test_locator.py -n
exit 1, no matches
```

### Residual

The pinned Pi 0.80.6 dependency-audit finding remains out of scope and was not changed.
