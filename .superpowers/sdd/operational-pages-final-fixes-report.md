# Operational Pages Final Fixes Report

## Status

DONE

Base reviewed through: `52bb270 fix: block unavailable inspector artifacts`

Release commit message: `fix: preserve exact operational page relations`

## Review findings resolved

- Flat `AgentEventRow` values are now first-class Inspector selections. Selecting an Agent row preserves its row ID, typed parent, turn, status, source, title, detail, exact relation sequence, lifecycle fields, and registered artifact references; it no longer immediately replaces the selection with a Business/context node.
- Related Inspector panels are scoped only by recorded facts: Context and execution use the exact row relation sequence, Evidence uses only artifact references present in the artifact index, and each panel renders an explicit unavailable reason when no exact relation is proven.
- Tool rows expose `start_sequence` and `end_sequence`, and their `source_sequence` is the recorded completion/end relation when present (falling back to start only for an open tool). The UI presents both lifecycle endpoints and uses the recorded relation instead of `min(source_sequences)`.
- Context request input is public only when its exact reference is registered in the artifact index, verified, available, and safe for public display. Page summaries and exact detail responses persist the reason when the action is unavailable; Context and Inspector do not construct an artifact URL in that state.
- The packaged workbench bundle and the single intentionally changed Agent lifecycle visual baseline were rebuilt.

## TDD evidence

### RED — tool completion relation and verified request registration

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py -q -k 'agent_tool_row_preserves_recorded_completion_relation or context_request_input_requires_verified_artifact_registration'
```

Observed before implementation: 2 failures. The tool row used sequence 48 instead of the recorded completion/producer relation at 49 and did not expose lifecycle fields; the context page reported an unverified request artifact as available.

### RED — first-class Agent selection and unavailable request actions

```sh
npm test --prefix packages/trajectory-workbench -- --run src/audit/selection.test.ts src/views/AgentView.test.tsx src/views/ContextView.test.tsx src/components/audit/AuditInspector.test.tsx src/app/App.test.tsx
```

Observed before implementation: 6 failures and 58 passes. A selected flat Agent row did not resolve, activation invoked sequence navigation and became `business:sequence-49`, and unverified request input still exposed Context/Inspector links without its persisted reason.

### Focused GREEN

The same backend regression selection passed 2 tests (9 deselected). The same frontend selection passed 65 tests across 5 files. The Agent relation integration test includes a Business node at the same sequence and verifies that the URL and Inspector retain the Agent row while Context, execution, and Evidence request only its recorded relations.

## Fresh verification

```sh
npm test --prefix packages/trajectory-workbench
```

Result: 19 files passed, 120 tests passed.

```sh
npm run check --prefix packages/trajectory-workbench
```

Result: exit 0 (`tsc -b --pretty false`).

```sh
npm run test:e2e --prefix packages/trajectory-workbench
```

Result: 24 Playwright tests passed, including UI flows, accessibility, and reviewed visual snapshots.

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py packages/grid-agent/tests/trajectory/api/test_app.py -q
```

Result: 32 API tests passed.

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api packages/grid-agent/tests/trajectory/projections -q
```

Result: 91 trajectory API/projection tests passed.

```sh
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory
```

Result: 0 errors.

```sh
uv run --project packages/grid-agent ruff check packages/grid-agent/src/grid_agent/trajectory/api/app.py packages/grid-agent/src/grid_agent/trajectory/api/projection_pages.py packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/tests/trajectory/api/test_app.py packages/grid-agent/tests/trajectory/api/test_projection_pages.py
```

Result: all checks passed.

```sh
make test
```

Result: exit 0 — 519 grid-agent tests, 87 grid-simulator tests, and 24 pi-grid-tools tests passed. Existing Starlette/httpx and pandapower deprecation warnings remain.

```sh
make test-e2e
```

Result: 17 tests passed.

```sh
make validate
```

Result: exit 0 for both offline `task-required` and scripted-Pi `static-analysis-core` validation.

```sh
git diff --check
```

Result: exit 0.

## Repository-wide Pyright baseline

```sh
uv run --project packages/grid-agent pyright packages/grid-agent/src
```

Result: exit 1 with 29 errors, all confined to unmodified modules outside `grid_agent/trajectory`: `config/catalog.py`, `knowledge/offline.py`, `reporting.py`, and `validation/oracles.py`. The complete changed trajectory package passes Pyright with 0 errors; this task did not alter the unrelated baseline modules.

## Safety and worktree hygiene

- No simulator/network facts were inferred or introduced.
- Artifact actions remain constrained to verified artifact-index records and the run-scoped gateway.
- The pre-existing `docs/status/JOURNAL.md` modification is intentionally excluded from this atomic commit.
