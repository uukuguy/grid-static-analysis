# Trajectory Workbench Operational Pages Design

## Goal

Replace the Agent, Context, and Evidence views' shallow subpages with bounded, auditable operational work surfaces. Each view must support real server pagination, filtering, selection, retry, and causal navigation rather than rendering a one-shot projection or formatted JSON as its primary interaction.

## Scope

This upgrade covers the three non-Business trajectory views and the shared paging/selection plumbing they need. It preserves the existing desktop-first three-region audit layout, four-tab Inspector, immutable artifact gateway, and read-only same-origin API.

It does not add write operations, hidden model reasoning, provider payload access, arbitrary filesystem access, or fabricated relationships.

## Shared Paging and Selection Contract

### Read-only API

Agent, Context, and Evidence each expose a bounded GET endpoint with a common envelope:

```ts
interface ProjectionPage<T> {
  analysis_id: string;
  items: T[];
  older_cursor: string | null;
  has_older: boolean;
  first_sequence: number | null;
  last_sequence: number | null;
}
```

Each endpoint accepts an opaque `cursor` plus view-specific, allow-listed filters. A page contains at most 500 records and at most 2 MiB serialized data. Cursor identity binds the analysis ID, view, filters, projection fingerprint/version, and sequence boundary. A malformed, stale, foreign, tampered, or filter-mismatched cursor is rejected with the existing typed API error boundary.

The API never emits raw Pi/provider payloads, secrets, filesystem paths, unregistered artifacts, or hidden chain-of-thought. Artifact preview/download stays behind the existing registered-reference, in-run, regular-file, digest-checked gateway.

### Frontend paging state

All three work surfaces use the same state model as Business:

- initial loading / ready / empty / partial / corrupt / unsupported / network error;
- `Load older …` while a prior cursor exists;
- disabled loading state;
- failed older-page status that retains already-loaded rows and retries the exact failed cursor;
- abort controller plus captured run ID, sequence, filters, and cursor identity so late responses cannot overwrite a newer view;
- loaded count and sequence/revision range visible in the view.

Loaded pages merge by stable record ID and retain virtual scroll anchors. Every selection is represented by a stable node/reference/sequence identity, updates the URL where applicable, and synchronizes the timeline and Inspector only when the relationship is explicitly recorded.

## Agent Operational Work Surface

### Records and pagination

`GET /api/runs/{analysis_id}/agent` pages stable agent event rows, not a potentially unbounded nested turn. Rows preserve enough structural metadata to reconstruct a bounded tree/timeline: turn, step, request, retry, public response, and tool lifecycle entries. Parent IDs, levels, source sequence, status, and source are typed fields.

Supported filters are turn ID, lifecycle kind, status, tool capability, and bounded case-insensitive text query. The backend applies filters before paging. The client renders virtual rows and can reconstruct a tree only from rows whose typed parent relationship is present; missing parents show an explicit truncated-history marker instead of guessing hierarchy.

### Operator actions

- Filter by turn, request/tool lifecycle kind, outcome, capability, and text.
- Expand/collapse typed hierarchy; keyboard tree navigation remains roving-tabindex compliant.
- Load earlier execution events and retry the exact failed cursor.
- Select a request/tool/response to open its public Inspector summary, associated context sequence, and exact business relation when recorded.
- Navigate to a proven producing or consuming business sequence. If no causal relation is recorded, display an unavailable reason.

Raw request, response, or tool artifact files are not linked from execution rows. The Inspector's existing bounded Execution panel remains the only public execution summary surface.

## Context Operational Work Surface

### Records and pagination

`GET /api/runs/{analysis_id}/context` gains cursor paging over lightweight context-frame summaries ordered by source sequence. The existing `at_sequence` endpoint remains the exact detail lookup for a selected frame.

Summary filters are sequence range, revision range, frame kind/change presence, and recorded-request-input availability. The page does not embed full before/delta/after documents. Selecting one or two summaries fetches exact verified details through `?at_sequence=`.

### Operator actions

- Page backward through context frames; show loaded sequence and revision ranges.
- Filter by sequence/revision interval, changed/unchanged frame, and request-input availability.
- Search a typed summary label or event kind; no deep unbounded JSON scan.
- Move to previous/next recorded frame, jump to a valid sequence, and select a frame from the timeline.
- Pin two frames and render a structured revision comparison: keys added, removed, and changed. Comparison only operates on fetched authoritative frames.
- Render Before, Delta, and After as structured, collapsible key/value content. Safe raw JSON is secondary, explicitly labelled, and only reflects the selected frame.
- Open model-visible request input only through the registered artifact gateway; otherwise show the persisted unavailable reason.

## Evidence Operational Work Surface

### Records and pagination

`GET /api/runs/{analysis_id}/evidence` pages typed `EvidenceRecord` entries rather than returning the entire index. It supports allow-listed filters for artifact kind, source, verification status, producer/consumer sequence range, and current-selection relevance; it supports deterministic sort by producer sequence or verification status.

The response keeps reference, kind, source, verification status, safe relative display path, producer/consumer identities, and unavailability reason. It never includes file contents.

### Operator actions

- Filter by type, source, verified/unavailable status, producer/consumer sequence, and selected-node relevance.
- Page earlier records, retry the exact failed evidence cursor, and keep a virtualized table for large indexes.
- Select a record to synchronize producer/consumer sequence and the Inspector Evidence tab.
- Safely preview registered JSON, Markdown, or plain text with a bounded preview size and syntax-preserving presentation; download remains an explicit secondary action.
- Copy a stable reference and navigate to a recorded producer/consumer. Disabled actions identify the precise integrity/unavailability reason.

## Inspector and Responsive Behavior

The Inspector remains a single investigation surface. A selection from Agent, Context, or Evidence supplies stable facts to Overview/Evidence/Context/Execution and does not fabricate a Business parent. On screens below 800px, the same Inspector DOM is shown in the focus-trapped sheet; desktop and medium behavior remains unchanged.

All controls use 13px body text, 11px metadata, and ordinary headings no larger than 16px. Rows are compact, keyboard operable, and show status/source/range without oversized cards or empty decorative panels.

## Failure and Integrity Semantics

- `partial`: display recorded facts with a non-blocking diagnostic banner.
- `corrupt`: block untrusted content and present the diagnostic.
- `unsupported`: name the unsupported projection/version and leave retry disabled unless a new compatible server can respond.
- network error: retain safe loaded content and expose a named retry for only the failed request.
- unverified artifact: never preview/download; show its stored verification reason.
- unknown relationship: show explicit unavailability; never choose a nearest event, numeric ID coincidence, or whole parent turn.

## Acceptance Criteria

1. Agent, Context, and Evidence use real bounded cursor API pages with typed filters; no surface fetches an unbounded whole projection as its primary dataset.
2. Each surface has visible loaded range/count, load-older, loading, exact-cursor retry, and out-of-order response rejection.
3. Agent hierarchy, Context comparison/replay, and Evidence filtering/preview/navigation perform their listed actions on native and legacy runs whenever the recorded data supports them.
4. Missing/legacy/unverified data states are explicit and do not fabricate content or unsafe links.
5. 100k agent/context/evidence fixture cases keep mounted rows within the established virtual DOM bound and exercise an actual server-compatible cursor contract.
6. Unit/API tests cover cursor binding, filters, stale response rejection, selection synchronization, unavailable paths, and artifact preview authorization.
7. Playwright covers desktop density, 1024px resizable Inspector, 768px sheet, keyboard navigation, Axe checks, cursor retry, and native/legacy runs across all four main views.
8. `npm run check`, workbench unit/E2E/visual tests, trajectory API/projection tests, `make test`, `make test-e2e`, and `make validate` pass.
