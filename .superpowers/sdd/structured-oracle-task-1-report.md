# Structured Oracle Task 1 Report

## Status

Complete. Topology-fact validation now uses canonical successful `tool_result` trace events and evidence refs instead of parsing `answer_output` prose. Informational text oracles remain available for knowledge and limitation cases.

## Implementation

- Added `ToolResultEvent`, `declared_fields_match`, and `topology_branch_endpoints`.
- Removed the legacy `branch_endpoints` prose/regex topology oracle.
- Added a `ValidationCase` invariant requiring structured cases to declare exactly one required capability.
- Extended `TraceSummary` with canonical structured result events parsed from successful `tool_result` JSONL trace records.
- Added structured oracle evaluation errors:
  - `verification_trace_missing`
  - `verification_result_missing`
  - `verification_evidence_missing`
  - `structured_oracle_mismatch`
- Updated `topology-line-endpoints-001` to declare expected result fields rather than answer wording tokens.
- Added synthetic trace tests proving correct traces pass with neutral prose, wrong structured results fail despite polished prose, evidence is required, missing traces are reported deterministically, and failed tool results are not accepted as successful candidates.

## TDD Evidence

RED:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation/test_oracles.py -v
ImportError: cannot import name 'ToolResultEvent' from 'grid_agent.validation.oracles'
```

GREEN:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation -v
17 passed in 1.25s
```

## Verification

Diagnostics:

```text
uv run --project packages/grid-agent python -m py_compile validation/run.py packages/grid-agent/src/grid_agent/validation/oracles.py packages/grid-agent/src/grid_agent/validation/cases.py packages/grid-agent/tests/validation/test_oracles.py packages/grid-agent/tests/validation/test_run_harness.py packages/grid-agent/tests/validation/test_case_contract.py
passed
```

Focused tests:

```text
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation -v
17 passed in 1.25s
```

Full tests:

```text
make test
96 passed in 23.98s
8 passed, 4 warnings in 2.32s
pi-grid-tools node check passed
pi-grid-tools node test: 4 passed
```

E2E:

```text
make test-e2e
9 passed in 22.17s
```

Additional checks:

```text
git diff --check
passed
```

## Concerns

- LSP diagnostics tooling was not exposed in this session, so `py_compile` was used for modified Python files.
- Running `make test` and `make test-e2e` concurrently caused one transient e2e path-layout failure because both targets touched the same `runs/path-layout-e2e` runtime directory. Re-running `make test` by itself passed.

## Commit

Pending at report creation; final response will include the commit hash.
