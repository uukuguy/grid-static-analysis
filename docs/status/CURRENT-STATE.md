# Current State

## Project Snapshot

- Project: grid-static-analysis
- Current branch: main
- Theme-level focus: semantic pandapower capability foundation for evidence-backed static analysis
- Project route: direct
- Canonical worklist: `docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md`
- Active work package: none — WP-A integrated

## Current Architecture

- CLI: `grid-agent` returns a single JSON answer envelope on stdout; offline routing handles narrow informational requests before workspace creation.
- Agent path: Pi/LLM receives only direct `grid_*` domain tools, guides, and answer submission; language/entity interpretation stays with the model.
- Simulator: `gridctl` owns registered read-only IEEE-39 access, typed semantic capabilities, pandapower 3.4.0 execution, result persistence, and evidence.
- Integrity: online drafts declare `result_refs` and `claim_evidence_refs`; current-run documents, digests, contexts, and links are verified without parsing answer prose.
- Validation: deterministic offline and scripted Pi suites validate structured tool results, capability boundaries, evidence, and the output envelope; provider validation is opt-in.

## Open Problems (theme-level)

- WP-B scope is not approved; multi-network lifecycle, DC flow, and richer policy/risk work remain deferred.

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
- `skills/grid-static-analysis/SKILL.md` — agent operating manual

## Resume Instructions

1. Read this file, then `RESUME-NEXT-SESSION.md` and the tail of `JOURNAL.md`.
2. Run `git status --short` and `make doctor`.
3. Use `make test`, `make test-e2e`, and `make validate` before changing a verified boundary.
4. Treat WP-B as new, explicitly approved work; do not revive the retired GSE implementation.
