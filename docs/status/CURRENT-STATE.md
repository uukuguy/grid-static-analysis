# Current State

## Project Snapshot

- Project: grid-static-analysis
- Current branch: main
- Theme-level focus: provider-validated continuous Analysis baseline for post-v0.2 capability planning
- Project route: direct
- Canonical worklist: none — v0.2 baseline complete
- Active work package: none

## Current Architecture

- CLI: `grid-agent` returns a single JSON answer envelope on stdout; offline routing handles narrow informational requests before workspace creation.
- Agent path: Pi/LLM receives only direct `grid_*` domain tools, guides, and answer submission; language/entity interpretation stays with the model.
- Simulator: `gridctl` owns registered read-only IEEE-39 access, typed semantic capabilities, pandapower 3.4.0 execution, result persistence, and evidence.
- Integrity: online drafts declare primary `result_refs` and `claim_evidence_refs`; current-run documents, digests, immutable simulation contexts, and evidence-associated result links are verified without parsing answer prose.
- Context engineering: each simulator-backed question opens a typed, immutable simulation-environment context (registered model source, pandapower version, semantic version, network counts and context reference); batch reports render that actual context rather than a guessed label.
- Validation: deterministic offline/scripted suites and provider-backed continuous Analysis validate structured results, capability boundaries, evidence, reports, and the output envelope.

## Open Problems (theme-level)

- Post-v0.2 scope is not selected; multi-network lifecycle, DC flow, and richer policy/risk work remain deferred.

## Key Files

### State / handoff

- `docs/status/RESUME-NEXT-SESSION.md` — current session handoff
- `docs/status/JOURNAL.md` — append-only event log
- `docs/status/CURRENT-STATE.md` — this structural snapshot

### Implementation entry points

- `docs/TASK.md` — evaluation requirements and examples
- `Makefile` — supported setup, execution, validation, and test commands
- `docs/RUNBOOK.md` — runtime/provider/evidence operations
- `docs/MANUAL-VALIDATION.md` — human acceptance procedure aligned to Makefile
- `docs/architecture/analysis-context.md` — continuous Analysis context and report architecture
- `validation/questions/task.md.txt` — canonical provider-backed Analysis instruction set
- `skills/grid-static-analysis/SKILL.md` — agent operating manual

## Resume Instructions

1. Read this file, then `RESUME-NEXT-SESSION.md` and the tail of `JOURNAL.md`.
2. Run `git status --short` and `make doctor`.
3. Use `make test`, `make test-e2e`, and `make validate` before changing a verified boundary.
4. Start new work from tag `v0.2`; explicitly select scope before implementation and do not revive the retired GSE implementation.
