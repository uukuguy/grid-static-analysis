# Task 1 Review Fix Report

## Summary

- Current native manifests are recognized only by the exact native schema and
  fixed native event-stream path; their declared `question_id` and any other
  native metadata remain available on the parsed manifest.
- Legacy v0.2 discovery requires the importer-defined context and trace source
  files in addition to a strict legacy manifest, so a manifest-only directory
  is not exposed as a trajectory run.
- The catalog still resolves every admitted required file locally and rejects
  symlinks and directory escapes before it is listed or opened.

## TDD Evidence

- RED: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_catalog.py -q`
  produced four expected failures: native current fields fell through to the
  legacy classifier, manifest-only legacy lookalikes were admitted, and corrupt
  native streams were not recognized as native.
- GREEN: the same command — 7 passed.

## Verification

- `uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/api/models.py packages/grid-agent/src/grid_agent/trajectory/api/catalog.py packages/grid-agent/tests/trajectory/api/test_catalog.py` — passed.
- `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory/api/models.py packages/grid-agent/src/grid_agent/trajectory/api/catalog.py packages/grid-agent/tests/trajectory/api/test_catalog.py` — 0 errors, 0 warnings.
- `git diff --check` — passed.

## Scope

- Existing unstaged `.superpowers/sdd/task-5-report.md` and
  `docs/status/JOURNAL.md` changes were preserved.
