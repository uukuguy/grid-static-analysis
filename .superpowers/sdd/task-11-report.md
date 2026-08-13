### Task 11 Report: CLI and Makefile migration

Status: complete.

Implemented:

- Added `grid-agent analysis --instructions PATH` as the continuous analysis CLI entrypoint.
- Changed `grid-agent report --questions PATH` to delegate to the same analysis execution path without launching per-question `grid-agent run` subprocesses.
- Emitted exactly one stdout `AnswerEnvelope` for analysis/report commands; progress and diagnostics go to stderr.
- Kept analysis artifacts self-contained under `runs/<analysis_id>/`, with stdout `answer_output` set to the project-relative `report.md` path.
- Updated `make analysis` as the canonical Makefile target and made `make report` a compatibility alias.
- Updated operator docs for the continuous analysis workflow and removed old batch-output/report-path guidance.

Verification:

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py -q` → 18 passed.
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/test_console_target.py packages/grid-agent/tests/test_contracts.py -q` → 21 passed.
- `make help` → lists `make analysis` as canonical and `make report` as compatibility alias.
- `git diff --check -- packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py Makefile docs/RUNBOOK.md docs/MANUAL-VALIDATION.md` → passed.
- `python -m compileall -q packages/grid-agent/src/grid_agent/cli/app.py` → passed.

Notes:

- Existing unrelated dirty files were not modified or staged.
- The prior dirty Makefile `OUTPUT ?= validation/questions/output.jsonl` intent was superseded by the Task11 removal of external `OUTPUT`/`--output`; per-turn envelopes now live in the analysis directory at `output/answers.jsonl`.

Follow-up type-boundary fix:

- Replaced `PiRpcClient`'s concrete `RunWorkspace` constructor type with a minimal read-only `RpcWorkspace` protocol exposing the actual runtime need: `root_path`.
- Tightened `AnalysisRunner.PiSession.prompt_and_wait` from arbitrary `**kwargs` to the exact keyword-only callback signature used by `AnalysisRunner` and implemented by `PiRpcClient`.

Follow-up verification:

- `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/src/grid_agent/analysis/runner.py` → 0 errors.
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/analysis/test_runner.py -q` → 27 passed.
