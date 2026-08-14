# Unified Trajectory Platform Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved unified agent/business trajectory platform through five independently reviewable implementation plans.

**Architecture:** A Python-owned typed event spine is the only authoritative chronology. Native runtime capture, deterministic projections and legacy import, a loopback read-only API, and a React workbench are layered on that spine in dependency order; every layer has a standalone verification gate before its consumer begins.

**Tech Stack:** Python 3.12+, Pydantic 2.12, Typer, FastAPI 0.139, uvicorn 0.51, Node.js 22.19+, React 19.2, TypeScript 7, Vite 8, TanStack Virtual 3, pytest 9, Vitest 4, Playwright 1.62.

## Global Constraints

- `grid-agent` answer-producing commands keep exactly one stdout JSON object with `question_id` and `answer_output`; diagnostics remain on stderr.
- All numerical or network-specific claims remain under `gridctl`, `grid-capability` protocol `1.0`, pandapower `3.4.0`, and current-run evidence verification.
- Pi receives only project-defined grid tools, `grid_guide_open`, `grid_analysis_context_get`, `grid_record_decision`, and `grid_submit_answer`.
- Hidden chain-of-thought, shell, generic filesystem tools, arbitrary Python, raw pandapower objects, and legacy query aliases stay excluded.
- Historical run `runs/analysis-20260814T081822Z` is read-only and is never migrated or rewritten.
- Native durable events use `grid-run-event/1.0`; unknown required events stop trusted replay at the last valid sequence.
- Large request, response, Pi, result, tool-result, and evidence documents remain immutable sidecars referenced by the event spine.
- Historical replay ships before live streaming; no browser mutation or mid-run control is introduced.
- Use `apply_patch` for source edits, run the smallest focused red/green test first, and commit each completed task atomically.

---

## Plan Order and Gates

| Order | Plan | Independent deliverable | Entry gate for the next plan |
| --- | --- | --- | --- |
| 1 | `2026-08-14-trajectory-event-spine.md` | Typed/hash-chained recorder, fail-closed reader, immutable artifact registry | protocol/schema tests and recorder corruption tests pass |
| 2 | `2026-08-14-trajectory-native-capture.md` | Native Analysis runs capture requests, responses, tools, retries, decisions, claims, and context revisions | scripted continuous Analysis writes a replayable native spine |
| 3 | `2026-08-14-trajectory-projections-import.md` | Pure Agent/Business/Context/Artifact projections plus deterministic `v0.2` importer | mini fixture and actual golden run meet count/lineage assertions |
| 4 | `2026-08-14-trajectory-readonly-api.md` | Loopback FastAPI service with cursor pagination and allowlisted artifact access | API/security suite passes with no mutation routes |
| 5 | `2026-08-14-trajectory-workbench-ui.md` | Business-first polished React workbench with all four views | unit, accessibility, Playwright, visual, 100k-event, and full project gates pass |

## Cross-plan Interfaces

```text
RunEventRecorder.append(EventDraft) -> RunEvent
RunEventReader.read_prefix() -> ReplayPrefix
ImmutableArtifactRegistry.write_json(kind, identity, payload) -> ArtifactPointer

NativeCaptureAdapter.drain_provider_requests() -> None
NativeCaptureAdapter.on_raw_event(event) -> None
NativeCaptureAdapter.on_semantic_event(event, trace_sequence) -> None
ProjectionService.open_run(run_root) -> ProjectedRun
LegacyV02Importer(run_root).import_run() -> ImportedReplay

TrajectoryRunCatalog.list_runs() -> tuple[RunSummary, ...]
TrajectoryRunCatalog.open(analysis_id) -> ProjectedRun
ProjectionPager.page(records, cursor_state, limits) -> ProjectionPage
ArtifactGateway.open(artifact_ref) -> ArtifactResponse
FastAPI /api/* response models -> mirrored TypeScript API interfaces
```

No later plan may read a projection cache as authority or bypass `TrajectoryRunCatalog` and `ArtifactGateway` to expose arbitrary files.

## Execution Sequence

- [ ] **Step 1: Execute event-spine plan and record its verification commit**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_events.py packages/grid-agent/tests/trajectory/test_recorder.py packages/grid-agent/tests/trajectory/test_artifacts.py -q`

Expected: all protocol, recorder, reader, and artifact tests pass.

- [ ] **Step 2: Execute native-capture plan on the verified spine**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_capture.py packages/grid-agent/tests/analysis/test_runner.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q && npm test --prefix packages/pi-grid-tools`

Expected: native scripted Analysis produces request artifacts and a valid event chain without changing the stdout envelope.

- [ ] **Step 3: Execute projection/import plan and validate the golden run**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections packages/grid-agent/tests/trajectory/test_legacy_v02.py -q && uv run --project packages/grid-agent python scripts/validate_trajectory_golden.py runs/analysis-20260814T081822Z`

Expected: deterministic projection tests pass; golden validation reports 9 turns, 36 paired tool calls, and verified Q7 lineage.

- [ ] **Step 4: Execute read-only API plan**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api -q`

Expected: API, pagination, CSP, path traversal, absolute-path, symlink, and no-mutation tests pass.

- [ ] **Step 5: Execute Workbench plan and the complete release gate**

Run: `npm run check --prefix packages/trajectory-workbench && npm test --prefix packages/trajectory-workbench && npm run test:e2e --prefix packages/trajectory-workbench && make test && make test-e2e && make validate`

Expected: frontend type/unit/E2E/visual gates and all existing project gates pass.

## Completion Contract

Do not call the platform complete until all five plan gates pass in order and a fresh `grid-agent trajectory serve` session opens both a native fixture and `runs/analysis-20260814T081822Z`. Provider validation remains optional, billed, and requires explicit credentials.
