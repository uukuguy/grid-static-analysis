# Final Review Fix Report: malformed answer-audit regression coverage

## Scope

Addressed the sole final-review finding in the `non-blocking-answer-audit`
worktree. The only source test file changed was
`packages/grid-agent/tests/reporting/test_batch_report.py`. The pre-existing
`docs/status/JOURNAL.md` worktree modification was preserved and excluded from
the commit.

## Finding addressed

`read_answer_audit()` already converted an invalid `answer-audit.json` schema
into a safe report-side diagnostic, but there was no direct regression test.

## Test coverage

Added `test_read_answer_audit_returns_one_error_for_invalid_schema`. It writes
an `answer-audit.json` whose `diagnostics` field has the wrong schema, invokes
`read_answer_audit()`, and verifies that handling returns normally with exactly
one `error` diagnostic identifying the malformed file.

## TDD evidence

The production behavior was already present before this test-only fix, so a
meaningful RED state was not feasible: the newly added regression test passed
immediately. This is expected for coverage of an existing implementation and
does not indicate a missing test assertion.

## Verification

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/reporting/test_batch_report.py -k read_answer_audit_returns_one_error_for_invalid_schema -q
# 1 passed, 10 deselected

uv run --project packages/grid-agent pytest packages/grid-agent/tests/reporting/test_batch_report.py -q
# 11 passed

git diff --check
# clean
```

## Commit

The focused test and this report are committed together. No production code or
`docs/status/JOURNAL.md` was changed by this fix.

## Concerns

None. The test exercises invalid-schema handling directly and confirms the
single-diagnostic contract without changing runtime behavior.
