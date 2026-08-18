# Current State

## Project Snapshot

- Project: grid-static-analysis
- Current branch: main
- Theme-level focus: full pandapower 3.4.0 static-analysis capability maintenance
- Project route: direct
- Canonical worklist: `docs/superpowers/plans/2026-08-18-pandapower-static-analysis-full-capability.md`
- Active work package: none; the 24-row full-capability release is closed

## Current Architecture

- CLI: `grid-agent` writes exactly one JSON answer envelope to stdout; progress and diagnostics stay on stderr.
- Agent runtime: managed Pi exposes only project grid tools, guides, and bounded context/decision tools; the LLM boundary owns provider-specific formats, while `grid-agent` commits ordinary model final text with controller-bound current-turn result/evidence lineage.
- Canonical capture: Pi atomically persists provider-independent model inputs before provider I/O without waiting for observer acknowledgement.
- Native trajectory: a Python-owned typed event spine records model requests/responses, tools, decisions, claims, context revisions, results, and evidence as the authoritative chronology.
- Observation: polling skips already-seen request artifacts before parsing; projection, validation, and integrity diagnostics are deterministic consumers of recorded execution and cannot semantically replace simulator truth.
- Simulator: `gridctl` exclusively owns registered network access and deterministic pandapower 3.4.0 calculations through `grid-capability` protocol 1.0.
- Analysis context: bounded model-facing views retain active model, sourced constraints, reusable calculations, scenarios, facts, lineage, and explicit omission metadata.
- Reporting: reports render recorded simulator/tool results before model prose, preserve successful tool values in failed turns, and link persisted current-run result/evidence artifacts.
- Workbench: the loopback read-only trajectory API and Business/Agent/Context/Evidence workbench consume deterministic projections without mutating runs.
- Verification: unit, E2E, offline/scripted validation, and provider-backed continuous Analysis cover the stdout contract, capability boundary, trajectory replay, evidence, and reports.

## Open Problems (theme-level)

- No release-blocking capability gaps are known in the declared static-analysis scope.
- Pandapower/pandas emit upstream deprecation warnings in state-estimation and legacy network construction paths; these do not change current results.
- Provider latency remains externally variable; future changes must preserve non-blocking trajectory observation.

## Key Files

### Loaded every agent session

- `AGENTS.md` — repository contract and simulator boundary

### State / handoff

- `docs/status/RESUME-NEXT-SESSION.md` — current session handoff
- `docs/status/JOURNAL.md` — append-only durable event log
- `docs/status/CURRENT-STATE.md` — this structural snapshot
- `docs/status/DECISIONS.md` — architectural decision ledger

### Implementation entry points

- `packages/grid-agent/src/grid_agent/analysis/runner.py` — continuous Analysis orchestration
- `packages/grid-agent/src/grid_agent/trajectory/capture.py` — native Pi event/request observation
- `packages/grid-agent/src/grid_agent/analysis/projector.py` — simulator result projection into continuous context
- `packages/grid-agent/src/grid_agent/analysis/view.py` — bounded model-facing context view
- `packages/grid-agent/src/grid_agent/analysis/report.py` — native-event-backed report generation
- `packages/pi-grid-tools/src/model-request-capture.mjs` — canonical pre-provider request persistence
- `packages/pi-grid-tools/src/domain-tools.mjs` — bounded Pi grid/orchestration tools
- `packages/grid-simulator/src/grid_simulator/capabilities/` — deterministic simulator capabilities and contracts
- `configs/capabilities/pandapower-3.4.0-static-analysis.json` — executable product coverage source of truth
- `docs/status/climb/research-tree.md` — active autonomous implementation hypothesis state
- `packages/trajectory-workbench/` — read-only trajectory investigation UI
- `validation/questions/task.md.txt` — canonical provider-backed continuous Analysis suite
- `Makefile` — supported setup, execution, and verification commands

## Resume Instructions

1. Read this file, then `RESUME-NEXT-SESSION.md` and the tail of `JOURNAL.md`.
2. Run `git status --short`, `git log --oneline -5`, and `make doctor`.
3. Use `make test`, `make test-e2e`, and `make validate` before changing a verified boundary.
4. Use `runs/analysis-20260818T072653Z/` as the full 7/7 provider-backed semantic baseline and `runs/analysis-20260818T073514Z/` as the model-construction contract regression.
5. Preserve the invariant that observation and validation may diagnose primary execution but may not introduce provider backpressure or reject a valid answer.
