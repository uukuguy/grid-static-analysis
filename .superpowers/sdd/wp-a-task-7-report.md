# WP-A Task 7 Report

## Summary

Ported AC power flow, branch result ranking, and N-1 contingency analysis to executable semantic capability contracts.

## Implemented

- Added `grid_simulator.analyses` for AC result normalization, persisted result/evidence documents, branch ranking from persisted result JSON, and independent N-1 scenario execution.
- Advertised `analysis.powerflow.ac.run`, `result.branches.rank`, and `analysis.contingency.n_minus_one.run` only after schema and execution validation.
- Bound AC execution to explicit `ac-default-v1` solver profile defaults with contract-enumerated override values and bounds.
- Persisted complete normalized AC result documents with bus, branch, transformer, generator, load, external-grid, convergence, solver, loss, and provenance records.
- Implemented `result.branches.rank` over current-workspace `result_ref` without rerunning AC or reloading the model context.
- Implemented N-1 with stable branch refs resolved against the immutable context revision, deep-copy-per-scenario execution, scenario persistence before aggregation, and partial aggregate status for mixed scenario outcomes.
- Added typed `powerflow_non_converged` handling with non-retryable errors, diagnostics evidence/artifacts, and legal recovery actions:
  - `inspect_network_diagnostics`
  - `change_solver_profile`
  - `report_non_convergence`

## TDD Evidence

- Red run:
  - `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_powerflow.py packages/grid-simulator/tests/test_contingency.py packages/grid-simulator/tests/test_analysis_errors.py -v`
  - Result: 6 failed at unsupported semantic capability / missing typed non-convergence behavior.
- Green focused run:
  - Same command
  - Result: 6 passed.

## Verification

- `pyright packages/grid-simulator/src/grid_simulator/analyses.py packages/grid-simulator/src/grid_simulator/operations.py packages/grid-simulator/src/grid_simulator/engine.py packages/grid-simulator/tests/conftest.py packages/grid-simulator/tests/test_powerflow.py packages/grid-simulator/tests/test_contingency.py packages/grid-simulator/tests/test_analysis_errors.py packages/grid-simulator/tests/test_protocol.py`
  - Result: 0 errors, 0 warnings, 0 informations.
- `ruff check packages/grid-simulator/src/grid_simulator/analyses.py packages/grid-simulator/src/grid_simulator/operations.py packages/grid-simulator/src/grid_simulator/engine.py packages/grid-simulator/tests/conftest.py packages/grid-simulator/tests/test_powerflow.py packages/grid-simulator/tests/test_contingency.py packages/grid-simulator/tests/test_analysis_errors.py packages/grid-simulator/tests/test_protocol.py`
  - Result: all checks passed.
- `uv run --project packages/grid-simulator python -m compileall -q packages/grid-simulator/src packages/grid-simulator/tests`
  - Result: passed.
- `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -v`
  - Result: 73 passed, 10 pandapower deprecation warnings.
- `make test`
  - Result: agent tests 97 passed; simulator tests 73 passed with 10 pandapower deprecation warnings; Pi tool checks passed; Node tests 4 passed.

## Notes

- The pandapower warnings are existing runtime deprecation warnings for `tap_dependency_table` in the packaged IEEE-39 network data path.
- LSP-specific diagnostics tooling was not exposed in this session; `pyright` was available locally and was used as the diagnostics substitute on all modified Python files.
