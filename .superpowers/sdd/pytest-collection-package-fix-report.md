# Pytest Collection Package Fix Report

## Root Cause

`tests/trajectory` was a package, but its `api` and `projections` subdirectories
were not. Pytest therefore imported duplicate test basenames as top-level
modules, producing import-file mismatches for `test_app.py` and
`test_artifacts.py` during collection.

## TDD Evidence

- RED: `make test` failed during collection with import-file mismatches for
  `tests/trajectory/api/test_app.py` and
  `tests/trajectory/projections/test_artifacts.py`.
- GREEN: added empty package markers to both immediate subdirectories, matching
  the existing `tests` package-marker convention.

## Verification

- `uv run --no-sync --project packages/grid-agent pytest
  packages/grid-agent/tests/trajectory --collect-only -q` — 208 tests
  collected; no import-file mismatch.
- `uv run --no-sync --project packages/grid-agent pytest
  packages/grid-agent/tests/trajectory/api/test_app.py
  packages/grid-agent/tests/trajectory/api/test_artifacts.py
  packages/grid-agent/tests/trajectory/projections/test_artifacts.py -q` —
  29 passed (with the pre-existing FastAPI/TestClient deprecation warning).
- The first `make test-agent` and `make test` attempts were blocked before
  collection by a concurrent missing `src/grid_agent/trajectory/static` forced
  include. After that directory was restored by concurrent work, both gates
  advanced through package installation and test execution; their full-suite
  completion remains outside this narrowly scoped collection repair.

## Scope

- No production code, pytest configuration, or global import mode changed.
