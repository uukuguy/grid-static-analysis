# Task 12 Report: Maintained architecture contract and continuous E2E

## Status

Completed and committed after the Task11 compatibility regression fix at `5c53fd5`.

## Implemented

- Added `docs/architecture/analysis-context.md` as the maintained analysis-context architecture contract.
- Added a contract test that verifies the architecture document names both checked-in schemas and every normative `EventType`.
- Added `packages/grid-agent/tests/e2e/test_continuous_analysis.py`, a one-process scripted Pi E2E with three ordered prompts:
  1. AC power flow through real workspace-local `gridctl`.
  2. Ranking with the exact prior power-flow `result_ref`.
  3. N-1 on the highest-ranked branch.
- Added copied input/output, context ledger, final report, compact trace, replay, single-process marker, and context lineage assertions.
- Fixed `PiRpcClient` to keep one persistent stdout reader per process, preventing the previous per-prompt reader from consuming later prompt events in a long-lived Pi process.
- Added `test_rpc_handles_two_sequential_prompts_in_one_process` as a regression test for the persistent Pi reader behavior.
- Updated the existing semantic Pi E2E only as needed for the current report/analysis CLI path and current RPC event shape.

## Verification Completed

```sh
make doctor
```

Result: exit 0.

```json
{"gridctl": "/Users/sujiangwen/sandbox/LLM/speechless.ai/SGAI/grid-static-analysis/packages/grid-simulator/.venv/bin/gridctl", "live_probe": false}
```

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/contract/test_analysis_context_docs.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py \
  packages/grid-agent/tests/runtime/test_rpc.py -q
```

Result: `15 passed in 14.59s`.

```sh
make test
```

Result: exit 0.

- grid-agent: `243 passed in 56.75s`
- grid-simulator: `79 passed, 18 warnings in 28.86s`
- pi-grid-tools: `14` Node tests passed

```sh
make test-e2e
```

Result: `16 passed in 38.77s`.

```sh
make validate
```

Result: exit 0 for offline `task-required` and scripted-Pi `static-analysis-core` validation suites.

No billed provider validation was invoked.

## Reviewer Strengthening Follow-up

Added continuous E2E assertions for:

- copied input bytes, copied path, source path, SHA-256 hash, and instruction count;
- each turn's archived `answer_path` existence and exact `answer_output` match against `output/answers.jsonl`;
- report projection coverage for the baseline heading, every turn answer, reused power-flow result ref, N-1 result ref, and one context revision line per turn.

Verification:

```sh
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/contract/test_analysis_context_docs.py \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py \
  packages/grid-agent/tests/runtime/test_rpc.py -q
```

Result: `15 passed in 14.65s`.

```sh
make test-e2e
```

Result: `16 passed in 38.80s`.
