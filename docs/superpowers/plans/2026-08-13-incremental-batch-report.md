# Incremental Batch Report Implementation Plan

**Goal:** Make each completed batch question immediately visible in the report, optional JSONL, and terminal trace.

**Architecture:** Retain completed records in memory, atomically refresh Markdown after every record, and append plus flush each optional JSONL envelope. Child stderr remains live; the parent adds explicit question start/end boundaries.

## Task 1: Incremental report persistence and visible question boundaries

**Files:** `packages/grid-agent/src/grid_agent/cli/app.py`, `packages/grid-agent/src/grid_agent/reporting.py`, `packages/grid-agent/tests/reporting/test_batch_report.py`, `docs/MANUAL-VALIDATION.md`.

1. Add failing tests for a one-record JSONL append and formatted `问题 N/M` boundary.
2. Run focused tests; confirm missing functions fail.
3. Add `append_jsonl_record`, initialize optional output before processing, append/flush it after each child, and atomically replace Markdown after each record.
4. Emit start/end boundaries around each child's live stderr stream.
5. Run focused tests, `make test-e2e`, `make validate`, and `git diff --check`.
6. Commit and push after recording the state journal.
