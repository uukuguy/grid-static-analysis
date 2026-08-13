### Task 10 Report: One-process Analysis runner

Status: complete

Implemented `AnalysisRunner` with dependency injection for the existing workspace, durable context store, turn controller, projector, Pi RPC session, context view materialization, and report writer.

Key behavior covered:

- Starts Pi exactly once per `AnalysisRunner.run(...)` and always stops it in `finally`.
- Runs ordered instructions through one Pi session.
- Materializes and injects the latest controller context view before every prompt.
- Finalizes each turn and checkpoints the report before sending the next prompt.
- Treats missing `grid_submit_answer` drafts as non-terminal failed turns.
- Treats `PiProtocolError`, durable context-state failures, and `SimulatorIntegrityError` as terminal analysis failures.
- Keeps normal gridctl/tool errors non-terminal as diagnostic/limitation context.
- Appends `analysis.completed` only after successful turns, replays/verifies durable state, writes final report, and writes `manifest.json`.

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

Commit:

- Pending at report-write time; expected message: `feat: run ordered instructions in one pi session`
