# Operational Pages Task 5 Report

## Status

DONE

Base reviewed through: `37f4527 fix: bind context detail to filter identity`

Release commit message: `feat: operate paged trajectory evidence and context`

## Scope delivered

- Rebuilt Evidence as a bounded virtual treegrid over the typed paged projection, with Kind, Source, Verification, sequence-range, Relevant reference, and Sort controls.
- Added page count/range feedback, Load older, and exact opaque-cursor Retry controls using the existing filter-bound operational page state.
- Added Copy reference and producer/consumer navigation. Navigation uses only the sequences recorded on the evidence record.
- Added a display-only preview helper that requests an already-authorized artifact-gateway URL with `Range: bytes=0-131071`, retains at most 131,072 bytes even when a server ignores Range, accepts only JSON/Markdown/plain text, and marks truncated responses.
- Restricted Preview, Download, and artifact URL construction to records whose `verification_status` is `verified`. Unavailable records show their persisted reason and expose no actionable URL.
- Invalidated in-flight previews when the run/filter request identity changes, preventing a late response for the same reference from crossing an investigation boundary.
- Added a 1,000-record Evidence browser fixture with opaque cursor paging, a one-shot older-page failure, safe partial-content artifact responses, and explicit verified/unavailable records.
- Added full Evidence Playwright/Axe and visual coverage, refreshed affected reviewed baselines, updated the operator guide, and rebuilt the packaged static UI.

## TDD evidence

### RED 1 — safe preview contract

Command:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/evidence/preview.test.ts src/views/DrilldownViews.test.tsx src/app/App.test.tsx
```

Observed: the preview suite could not resolve the missing `src/evidence/preview` module, and the old Evidence view had neither verified-only preview controls nor the new paged-row interface.

### GREEN 1

The preview helper and Evidence workflow passed focused tests for the byte Range, client-side byte cap, fixed safe media types, failed responses, unavailable blocking, filters, copy, preview, download, and recorded lineage navigation.

### RED 2 — stale preview identity

A regression test opened a preview in `run-a`, changed the preview identity to `run-b` while retaining the same evidence reference, and then resolved the old promise. It failed because the old `{"stale":true}` content appeared in the new view.

### GREEN 2

Evidence now increments its request generation and clears the drawer whenever the run/filter identity changes. The focused drill-down suite passed 4/4 after the fix.

## Fresh release verification

```sh
npm test --prefix packages/trajectory-workbench
```

Result: 19 files passed, 114 tests passed.

```sh
npm run check --prefix packages/trajectory-workbench
```

Result: exit 0 (`tsc -b --pretty false`).

```sh
npm run test:e2e --prefix packages/trajectory-workbench
```

Result: 24 Playwright tests passed, including the Evidence paging/retry/preview/navigation/Axe workflow.

```sh
npm run test:visual --prefix packages/trajectory-workbench
```

Result: 11 reviewed visual tests passed.

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api packages/grid-agent/tests/trajectory/projections -q
```

Result: 89 tests passed, with one existing Starlette/httpx deprecation warning.

```sh
make doctor
```

Result: exit 0; the managed `gridctl` was found in the simulator environment.

```sh
make test
```

Result: exit 0 — 517 grid-agent tests, 87 grid-simulator tests, and 24 pi-grid-tools tests passed. Existing Starlette and pandapower deprecation warnings remain.

```sh
make test-e2e
```

Result: 17 tests passed.

```sh
make validate
```

Result: exit 0 — offline `task-required` passed 8/8 and scripted-Pi `static-analysis-core` passed 10/10.

```sh
git diff --check
```

Result: exit 0.

## Fresh native and legacy browser verification

A new loopback-only trajectory server was started against a temporary validation catalog containing:

- a freshly generated native run with simulator artifacts; and
- an immutable copy of `runs/analysis-20260814T081822Z` from the main worktree.

Observed in a real Chromium session:

- Native Agent, Context, and Evidence pages loaded and filtered; Context `changed=true` returned the recorded changed frame.
- Verified native evidence opened a registered JSON preview and downloaded through the artifact gateway.
- Producer navigation selected the exact recorded Business sequence and synchronized the Inspector.
- An unavailable native record exposed only its persisted reason and Copy reference action.
- Legacy Evidence loaded 13 unavailable records with persisted reasons and no preview/download controls; legacy Agent loaded 9 filtered events and Context loaded 123 changed frames.
- The synthetic one-shot paging failure and exact-cursor retry were exercised by the Playwright fixture because the real server correctly does not inject failures.

Temporary catalogs, browser output, and downloaded artifacts were removed after verification; the source legacy run was only read/copied.

## Security self-review

- Preview and download continue to use only the run-scoped registered artifact gateway; no filesystem path or generic fetch surface was introduced.
- The UI never calls `artifactUrl` for unavailable records.
- Preview rejects executable/unexpected content types and unsuccessful responses before reading a body.
- Preview caps retained bytes independently of server Range support and treats content as inert `<pre>` text.
- Page retry reuses the stored opaque cursor and cannot combine it with a different filter identity.

## Concerns

- No blocking concerns.
- The local `pi-grid-tools` dependency install reports four transitive npm audit findings (two moderate, two high); package versions remain lockfile-pinned and were not changed by this task.
- Existing Starlette/httpx and pandapower deprecation warnings are unchanged.
- The pre-existing `docs/status/JOURNAL.md` modification is intentionally excluded from the release commit.

## HIGH review fix — unavailable Inspector artifact links

Root cause: the main Evidence view gated artifact URL creation on `verification_status === 'verified'`, but the Audit Inspector's independent `EvidenceCard` rendering path always called `artifactUrl(record.reference)` and rendered a download anchor. Selecting an unavailable record could therefore construct and expose an actionable gateway URL despite the release contract.

TDD RED:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/components/audit/AuditInspector.test.tsx
```

Observed: the new unavailable-evidence regression found a download anchor with `/artifact/evidence:legacy-unavailable`; the expected blocked text was absent. The test also records that `artifactUrl` must remain uncalled.

Fix: `EvidenceCard` now branches on the exact verified status before evaluating the URL builder. Verified records retain their download link. Unavailable records render their persisted reason (or the same safe fallback used by Evidence) and `Download blocked.`, with no anchor or URL construction.

Focused GREEN:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/components/audit/AuditInspector.test.tsx
```

Result: 1 file passed, 6 tests passed.

```sh
npm run check --prefix packages/trajectory-workbench
```

Result: exit 0 (`tsc -b --pretty false`).
