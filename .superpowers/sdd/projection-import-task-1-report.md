# Projection/import Task 1 report: common replay and projection models

Date: 2026-08-15

Status: implemented and verified

## Scope

Implemented only Task 1 of `2026-08-14-trajectory-projections-import.md`: the
explicitly distinct imported-event envelope and the strict, frozen common
projection output models. No importer, projector, cache, service, runtime, or
historical-run data was changed.

## TDD evidence

### RED

`uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py -q`

Before production files existed, test collection failed as expected with:
`ModuleNotFoundError: No module named 'grid_agent.trajectory.projection_models'`.

### GREEN

The same focused command passed with `4 passed` after the minimal models were
implemented.

## Implementation

- Added `ReplayEventLike`, a runtime-checkable protocol shared by native and imported validated replay events.
- Added frozen, extra-forbidden `SourceCoordinate` and `ImportedRunEvent` models. Imported events retain nullable timestamps, their own `grid-run-import-event/1.0` schema, source coordinates, normalization hashes, and require `observed`/`importer-integrity` provenance.
- Added frozen output models for agent, business, context, artifact, diagnostic, and assembled-run projections.
- Enforced business derived-node provenance (`rule_id` and nonempty source sequences); observed and agent-declared business nodes cannot claim a rule.
- Enforced ordered context revisions and explicit unavailable reasons whenever a frame has no request artifact reference.

## Verification

`uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py packages/grid-agent/tests/trajectory/test_events.py packages/grid-agent/tests/trajectory/test_reader.py -q` passed: `47 passed in 0.36s`.

`ruff check` passed for the owned files; `pyright` reported `0 errors, 0 warnings`; `git diff --check` passed.

## Concerns

None. Future tasks own event reduction, cache materialization, source-file import, and service orchestration.
