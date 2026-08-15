# Trajectory Audit Upgrade — Final Review Fix Report

Date: 2026-08-15

Status: DONE

Commit: the atomic commit containing this report, with subject `fix: close trajectory audit review gaps`; the final hash is reported in the handoff because a Git commit cannot contain its own hash.

## Changed scope

- Replaced whole-`BusinessProblem` HTTP paging with `business-trajectory/1.1` causal rows. Each record is cursor-addressed by one canonical source sequence, repeats only fixed problem metadata (`first_sequence`, `last_sequence`, `node_count`), and carries only the nodes caused at that sequence. The existing pager still enforces 500 records and 2 MiB per response.
- Added a frontend causal-row importer that reconstructs the loaded portion of stable problem groups, de-duplicates retried rows by durable row ID, and preserves the total node count without reconstructing an unbounded sequence array.
- Added `analysis_id` to projection page envelopes. Business, agent, context, evidence, execution, and older-business request paths now capture the requested run/sequence, pass and honor `AbortSignal`, and reject late or identity-mismatched responses before updating state.
- Added artifact-backed execution lineage through verified `ArtifactIndexRecord` identities and recorded tool result/evidence refs. Artifact-backed slices require an exact turn → step → request → tool/response chain; missing, ambiguous, unverified, mismatched, nearest, and numeric-ID-only relations remain explicitly unavailable.
- Made `ReplayEventLike` a read-only projection protocol, matching immutable native/imported events and fixtures. Pyright now checks the real covariance contract without casts, ignores, or weakening fixture immutability.
- Updated the real-contract 100k browser fixture to return consecutive 500-row pages from the same 100k-node problem and to retry the exact opaque cursor. Updated the four affected visual baselines from an unbounded sequence label to the stable first/last range.
- Rebuilt the packaged workbench asset. No CSS, provider payload, secret, arbitrary path, registry/gateway, write-route, or CORS boundary changed.

## TDD RED evidence

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py::test_business_api_pages_causal_rows_inside_one_large_problem_with_exact_cursor -q` — failed before implementation because the server attempted to page the whole >2 MiB problem and returned HTTP 409.
- `npm test --prefix packages/trajectory-workbench -- --run src/api/business.test.ts` — failed before implementation because the bounded causal-row importer did not exist.
- `npm test --prefix packages/trajectory-workbench -- --run src/app/App.test.tsx -t 'out-of-order'` — the three new business/context/evidence ordering cases failed before the request-identity guards were added.
- The new projection/API/artifact lineage regressions initially failed because artifact records did not populate result/claim identity and claim sequence 60 returned no exact tool/request chain. The new Inspector regression initially exposed the unrelated same-turn descendants.
- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_agent.py::test_execution_slice_scopes_claim_execution_by_exact_artifact_lineage_ids -q` — after adding the mismatched-tool negative, failed because a valid turn/request plus non-existent tool ID still returned a partial turn.
- `uv run --project packages/grid-agent pyright packages/grid-agent/tests/trajectory/projections/test_agent.py` — initially reported four writable-protocol/invariant-payload errors. A broader trajectory scan confirmed the protocol, not immutable fixtures, was the common cause.

## GREEN focused evidence

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/projections/test_artifacts.py -q` — 29 passed.
- Exact artifact lineage projection and API tests — 2 passed, including the mismatched-tool explicit-unavailable negative.
- `npm test --prefix packages/trajectory-workbench -- --run src/app/App.test.tsx -t 'out-of-order'` — 3 passed.
- `npm test --prefix packages/trajectory-workbench -- --run src/api/business.test.ts src/components/audit/AuditInspector.test.tsx src/app/App.test.tsx` — 3 files, 40 tests passed.
- `npm run test:e2e --prefix packages/trajectory-workbench -- --grep '100k trajectory'` — 1 passed; the retried request repeated the exact cursor and the UI reconstructed 1,000 loaded causal rows while mounting at most 120 list items.
- `uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory packages/grid-agent/tests/trajectory` — 0 errors, 0 warnings.

## GREEN broad and release evidence

- `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q` — 219 passed; one upstream Starlette/httpx deprecation warning.
- `make test` — grid-agent 508 passed; grid-simulator 87 passed with 18 upstream pandapower deprecation warnings; pi-grid-tools 24 passed.
- `npm run check --prefix packages/trajectory-workbench` — passed.
- `npm test --prefix packages/trajectory-workbench` — 14 files, 83 tests passed.
- `npm run test:e2e --prefix packages/trajectory-workbench` — 19 passed, including visual, accessibility, GET-only, exact-cursor, and claim investigation coverage.
- `make test-e2e` — 17 passed.
- `make validate` — offline `task-required` and scripted-Pi `static-analysis-core` both completed successfully.
- `make build-workbench` — TypeScript build and Vite packaging passed; packaged `app.js` rebuilt.
- `git diff --check` — passed.

## Remaining concerns

- No known functional or security concern remains in this fix scope.
- Verification emitted only upstream deprecation/version notices (Starlette/httpx, pandapower, Pyright update availability, and Playwright `NO_COLOR`/`FORCE_COLOR`).
- Optional billed provider validation was not run because no explicit provider credentials were requested.
- The pre-existing uncommitted `docs/status/JOURNAL.md` edit is intentionally excluded from this commit.
