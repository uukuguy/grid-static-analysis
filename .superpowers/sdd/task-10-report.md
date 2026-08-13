### Task 10 Report: One-process Analysis runner

Status: complete; final review fixes complete

Implemented `AnalysisRunner` with dependency injection for the existing workspace, durable context store, turn controller, projector, Pi RPC session, context view materialization, and report writer.

Key behavior covered:

- Starts Pi exactly once per `AnalysisRunner.run(...)` and always stops it in `finally`.
- Runs ordered instructions through one Pi session.
- Materializes and injects the latest controller context view before every prompt.
- Finalizes each turn and checkpoints the report before sending the next prompt.
- Treats missing `grid_submit_answer` drafts as non-terminal failed turns.
- Treats `PiProtocolError`, durable context-state failures, and `SimulatorIntegrityError` as terminal analysis failures.
- Protects Pi launch inside the lifecycle guard so launch failures terminalize artifacts and still call `stop`.
- Safely aborts active turns on durable `ContextStoreError` before writing a failed manifest when the store can still record closure.
- Keeps normal gridctl/tool errors non-terminal as diagnostic/limitation context.
- Verifies the materialized running snapshot and replay/in-memory consistency before appending `analysis.completed`, preventing completed context plus failed outcome contradictions.
- Appends `analysis.failed` and writes failed report/manifest when pre-completion integrity verification fails.

Files changed:

- `packages/grid-agent/src/grid_agent/analysis/runner.py`
- `packages/grid-agent/tests/analysis/test_runner.py`

Verification:

- RED: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - Failed as expected with `ModuleNotFoundError: No module named 'grid_agent.analysis.runner'`.
- GREEN targeted: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - `6 passed in 0.16s`
- Analysis suite: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis -q`
  - `75 passed in 6.07s`
- Full offline gate: `make test`
  - grid-agent: `237 passed in 50.74s`
  - grid-simulator: `79 passed, 18 warnings in 28.92s`
  - pi-grid-tools: `14 passed`
- Review-fix RED: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - Failed as expected on unhandled Pi launch failure, active-turn durable error, and final verification ordering.
- Review-fix runner tests: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - `9 passed in 0.16s`
- Review-fix Analysis suite: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis -q`
  - `78 passed in 6.18s`
- Review-fix pyright: `pyright --pythonpath packages/grid-agent/.venv/bin/python packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/tests/analysis/test_runner.py`
  - `0 errors, 0 warnings, 0 informations`
- Review-fix mypy: `uv run --project packages/grid-agent --with mypy mypy packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/tests/analysis/test_runner.py`
  - `Success: no issues found in 2 source files`
- Final high-issue RED: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - Failed as expected because final verification still happened after `analysis.completed` and produced completed context with failed outcome.
- Final high-issue runner tests: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`
  - `9 passed in 0.22s`
- Final high-issue pyright: `pyright --pythonpath packages/grid-agent/.venv/bin/python packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/tests/analysis/test_runner.py`
  - `0 errors, 0 warnings, 0 informations`
- Final high-issue mypy: `uv run --project packages/grid-agent --with mypy mypy packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/tests/analysis/test_runner.py`
  - `Success: no issues found in 2 source files`

Commit:

- Initial implementation: `624e2aa feat: run ordered instructions in one pi session`
- Review fixes: `f88b51b fix: harden analysis runner terminal failures`
- Final high-issue fix pending at report-update time.
