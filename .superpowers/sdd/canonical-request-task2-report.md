# Canonical Request Task 2 Report

## Scope

- Implemented the pre-I/O model request commit acknowledgement client.
- Added the internal `.grid-agent/trajectory-acks/<analysis-id>/` path contract and `GRID_AGENT_TRAJECTORY_ACKS` launch environment.
- Removed `GRID_AGENT_PROVIDER_ID` and `GRID_AGENT_MODEL_ID` from native capture launch environment.
- Added verified Pi runtime identity environment values when the command identity has complete verified source metadata.
- Updated the extension and continuous-analysis launch integration so the acknowledgement path reaches the capture hook.
- Did not implement Python recorder ingestion or acknowledgement writing; that remains Task 3.

## TDD Evidence

### RED

Command:

```sh
npm test --prefix packages/pi-grid-tools -- test/model-request-capture.test.mjs
```

Expected failures before implementation:

- Provider continuation ran before any acknowledgement.
- Malformed acknowledgement cases did not reject.
- Timeout case did not reject.

Command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/application/test_paths.py -q
```

Expected failures before implementation:

- `RuntimePaths` had no `trajectory_acks_path`.
- Pi launch did not expose verified runtime identity env values.
- `ProjectPaths` had no trajectory acknowledgement path.

### GREEN

Command:

```sh
npm test --prefix packages/pi-grid-tools -- \
  test/model-request-capture.test.mjs test/domain-tools.test.mjs
```

Result:

```text
tests 30
pass 30
fail 0
```

Command:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/application/test_paths.py -q
```

Result:

```text
9 passed
```

## Implementation Notes

- `model-request-capture.mjs` writes and fsyncs `input.json`, then waits for exactly `<acks>/<request_id>.committed.json`.
- The acknowledgement validator requires schema `grid-model-request-commit/1.0`, matching request id, matching semantic digest, `artifact:sha256:<digest>`, positive event sequence, and `committed` status.
- Polling defaults are 25 ms interval and 30 s monotonic deadline; tests use short overrides.
- `domain-tools.mjs` now treats `GRID_AGENT_TRAJECTORY_ACKS` as part of the all-or-none native capture configuration, but does not require it to be under `GRID_AGENT_WORKSPACE` because the ack directory is internal transport state under `.grid-agent`.
- `environment.py` creates the `trajectory-acks` parent and per-analysis ack directory with `0700` permissions and does not delete existing state.

## Verification

```sh
npm test --prefix packages/pi-grid-tools -- \
  test/model-request-capture.test.mjs test/domain-tools.test.mjs
```

Passed: 30 tests.

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/runtime/test_pi_config.py \
  packages/grid-agent/tests/application/test_paths.py -q
```

Passed: 9 tests.

```sh
node --check packages/pi-grid-tools/src/model-request-capture.mjs
node --check packages/pi-grid-tools/src/domain-tools.mjs
uv run --project packages/grid-agent python -m py_compile \
  packages/grid-agent/src/grid_agent/runtime/environment.py \
  packages/grid-agent/src/grid_agent/application/paths.py \
  packages/grid-agent/src/grid_agent/cli/app.py
```

Passed.

```sh
git diff --check
```

Passed.
