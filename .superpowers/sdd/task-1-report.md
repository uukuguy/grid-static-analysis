# Task 1 Report: Self-contained Analysis workspace

Date: 2026-08-13

Status: implemented and verified

## Scope

Built the new focused `grid_agent.analysis` workspace layer without changing the existing `RunWorkspace`. The implementation is limited to the Task 1-owned package and test files plus this report.

## Files added

- `packages/grid-agent/src/grid_agent/analysis/__init__.py`
- `packages/grid-agent/src/grid_agent/analysis/workspace.py`
- `packages/grid-agent/tests/analysis/__init__.py`
- `packages/grid-agent/tests/analysis/test_workspace.py`

## TDD evidence

### Red

Command:

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py -q
```

Observed failure:

```text
ModuleNotFoundError: No module named 'grid_agent.analysis'
```

### Green

Command:

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py -q
```

Observed result:

```text
2 passed in 0.02s
```

## Implementation details

### `AnalysisWorkspace`

Added a new immutable workspace model with the required exported paths:

- `manifest_path`
- `copied_instructions_path`
- `answers_path`
- `report_path`
- `context_snapshot_path`
- `context_events_path`
- `trace_path`
- `turns_path`
- `evidence_path`
- `results_path`
- `tool_results_path`
- `bin_path`
- `pi_path`
- `active_turn_path`
- `active_answer_draft_path`
- `context_view_path`

`AnalysisWorkspace.create(root, analysis_id=None)` now:

- uses `analysis-YYYYMMDDTHHMMSSZ` as the default UTC identifier
- creates a new analysis root with `mkdir(parents=True, exist_ok=False)`
- creates the focused analysis directory tree:
  - `input/`
  - `output/`
  - `context/`
  - `trace/`
  - `turns/`
  - `evidence/contexts/`
  - `evidence/network-facts/`
  - `evidence/analysis/`
  - `evidence/results/`
  - `tool-results/`
  - `bin/`
  - `pi/`

Added `turn_path(ordinal)` to create and return zero-padded turn directories like `turns/001`.

### `CopiedInstructions`

Added an immutable metadata model carrying:

- `source_path`
- `copied_path`
- `sha256`
- `instruction_count`

### Instruction copy semantics

Added `copy_instructions(source)` with the requested behavior:

- reads the source as raw bytes
- preserves bytes exactly in `input/instructions.md.txt`
- computes SHA-256 on the copied bytes
- counts instructions using the same semantics as `load_questions`
  - trim each line
  - ignore blank lines
  - ignore comment lines starting with `#` after left trim
  - raise if there are no instructions
- flushes and `fsync`s the copied file
- allows idempotent re-copy of identical bytes
- raises `RuntimeError` when the destination already contains different bytes

## Design choices

- Kept the analysis workspace independent from `RunWorkspace` as requested.
- Reimplemented the question-counting semantics locally instead of importing report-generation code, to keep the new workspace layer focused and avoid unnecessary coupling.
- Returned `copied_path` relative to the analysis root (`input/instructions.md.txt`), which matches the later Analysis plan examples.

## Verification summary

- Focused Task 1 pytest target passes.
- No unrelated files were modified by this implementation.
- Existing dirty worktree changes outside Task 1 were left untouched.

## Commit

Pending at report-write time; created immediately after this report is staged with the Task 1 files.

## Concerns

- The task brief did not require manifest contents yet, so `manifest.json` is currently represented as a reserved path rather than eagerly written. Later tasks can safely materialize it when the controller has full metadata to record.
