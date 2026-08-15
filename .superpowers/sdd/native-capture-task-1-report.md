# Native Capture Task 1 Report: Exact pre-provider request capture

Date: 2026-08-14

Status: implemented and verified

## Scope

Implemented the Task 1 native-capture boundary only:

- Added Pi `before_provider_request` capture for the exact provider payload.
- Added durable immutable `requests/<request_id>/input.json` sidecars.
- Added native-capture runtime paths and public provider/model identifiers.
- Wired capture into the existing restricted domain-tools extension only when all
  three trajectory paths are configured.
- Preserved the existing CLI stdout answer envelope and registered Pi tool set.

## Files

- `packages/pi-grid-tools/src/trajectory-capture.mjs` (new)
- `packages/pi-grid-tools/test/trajectory-capture.test.mjs` (new)
- `packages/pi-grid-tools/src/domain-tools.mjs`
- `packages/grid-agent/src/grid_agent/runtime/environment.py`
- `packages/grid-agent/tests/runtime/test_pi_config.py`

## TDD evidence

### Initial RED

Command:

```sh
npm test --prefix packages/pi-grid-tools -- --test-name-pattern="capture" && \
  uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py -q
```

Observed Node failure:

```text
Error [ERR_MODULE_NOT_FOUND]: Cannot find module
packages/pi-grid-tools/src/trajectory-capture.mjs
```

The shell stopped at the expected Node failure, so the Python test was then run
directly.

Command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py -q
```

Observed Python failure:

```text
TypeError: RuntimePaths.__init__() got an unexpected keyword argument
'trajectory_requests_path'
1 failed, 5 passed
```

Two subsequent focused RED checks caught integration details before their production
changes: capture configuration without `active_turn_path` initially omitted the five
new environment keys, and the existing Analysis context's bare 64-hex state hash was
initially rejected.

### GREEN

Focused command:

```sh
npm test --prefix packages/pi-grid-tools -- --test-name-pattern="capture" && \
  uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py -q
```

Observed result:

```text
Node: 10 tests, 10 passed
Python: 6 passed
```

Broader related command:

```sh
node --check packages/pi-grid-tools/src/trajectory-capture.mjs && \
  npm test --prefix packages/pi-grid-tools && \
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime -q
```

Observed result:

```text
Node: 22 tests, 22 passed
Python runtime: 31 passed
```

Fatal-exit probe:

```sh
node --input-type=module -e \
  'import { captureFatal } from "./packages/pi-grid-tools/src/trajectory-capture.mjs"; \
  captureFatal("trajectory capture fatal probe")'
```

Observed result: stderr contained the diagnostic and the process exited with status
`86`.

## Implementation notes

- Request IDs use the active turn ID and a process-local, monotonically increasing
  request index: `<turn_id>-rNNN`.
- Each `grid-model-request-input/1.0` document contains the required provider/model,
  timestamp, native source sequences, context revision/hash, and the exact JSON
  provider payload.
- Payload validation rejects non-JSON values, cycles, unsafe credential-name keys,
  and hidden-reasoning content keys before any request document is created.
- Turn IDs are restricted to a traversal-safe identifier form. Capture state requires
  positive strictly increasing event sequences, a nonnegative revision, and the
  existing Analysis context's 64-hex state hash form.
- The request directory is claimed once. The compact recursively key-sorted JSON is
  written to a same-directory `wx` temporary file, file-synced, closed, renamed, and
  followed by directory fsyncs before the hook returns. Existing request paths are
  rejected rather than replaced.
- Any capture error routes to `captureFatal`, which writes a diagnostic to stderr and
  exits the Pi child with status 86. The hook never substitutes or modifies the
  provider payload.
- The Python launcher exposes the five new capture environment keys only when all five
  capture fields are configured. Provider credentials remain confined to their
  existing provider-specific environment entry and are not copied into trajectory
  metadata.

## Boundary review

- No shell, generic file, raw simulator, or legacy query capability was added to Pi.
- `domainToolsExtension` still registers only project-defined grid tools, the bounded
  guide/context tools, and answer submission.
- The Node extension writes only request sidecars; it does not write the authoritative
  event log.
- Existing unrelated modifications in `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` were left untouched.

## Concerns

No Task 1 correctness concern remains. Downstream native Analysis integration must
supply the new runtime paths and keep capture state current; that wiring belongs to
later tasks in the approved native-capture plan.
