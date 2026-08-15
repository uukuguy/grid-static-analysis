# Trajectory Workbench Operational Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Agent, Context, and Evidence into real bounded audit work surfaces with cursor paging, filtering, retry, stable selection, and their domain-specific investigation operations.

**Architecture:** Extend the existing signed cursor/pager boundary with typed flat page records for agent events, context summaries, and evidence records. The React client shares a filter-bound paging controller while each view renders its own virtualized, auditable operations. Exact detail remains a separate lookup (`context?at_sequence`) and artifact bytes remain exclusively behind `ArtifactGateway`.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, existing CursorCodec/ProjectionPager, React 19/TypeScript strict, TanStack Virtual, Vitest, Playwright/Axe, pytest/Pyright.

## Global Constraints

- API remains same-origin, loopback-only, GET-only, no CORS/WebSockets; malformed, foreign, stale, tampered, or filter-mismatched cursors use typed API errors.
- Every page has at most 500 records and at most 2 MiB; API page records contain public typed projection facts only.
- Do not emit or render raw Pi/provider payloads, credentials, hidden reasoning, arbitrary paths, or unregistered artifact bytes.
- Artifact preview/download uses only existing registered, in-run, regular-file, digest-checked `ArtifactGateway`; unverified records explicitly state why actions are unavailable.
- Late responses must not overwrite newer run, cursor, filter, or sequence state; failed older loads retry exactly the stored opaque cursor.
- Preserve compact 13px body/11px metadata/<=16px ordinary heading density, desktop/medium inspector behavior, and the single <800px focus-trapped Inspector sheet.
- Unknown lineage never falls back to nearest sequence, numeric ID coincidence, or whole parent turn.
- Every task records TDD RED, focused GREEN, broader declared gates, and an atomic commit.

---

### Task 1: Filter-bound flat projection page contracts

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/trajectory/projection_models.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/projection_pages.py`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/api/app.py`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/api/cursor.py`
- Modify: `packages/grid-agent/tests/trajectory/api/test_app.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_projection_pages.py`

**Interfaces:**

```python
class AgentEventRow(StrictFrozenModel):
    id: str; parent_id: str | None; turn_id: str; kind: str
    level: int; source_sequence: int; source: NodeSource
    status: LifecycleStatus; title: str; detail: str | None = None

class ContextFrameSummary(StrictFrozenModel):
    id: str; source_sequence: int; before_revision: int; after_revision: int
    changed: bool; request_input_available: bool; event_kind: str

def projection_page(
    projected: ProjectedRun, view: Literal['agent', 'context', 'evidence'],
    cursor: str | None, filters: Mapping[str, str | int | bool | None], codec: CursorCodec,
) -> ProjectionPageResponse: ...
```

The cursor fingerprint must include canonicalized allow-listed filters. Filter names are: Agent `turn_id`, `kind`, `status`, `capability`, `q`; Context `from_sequence`, `to_sequence`, `from_revision`, `to_revision`, `changed`, `request_input`; Evidence `kind`, `source`, `verification_status`, `from_sequence`, `to_sequence`, `relevant_ref`, `sort`.

- [ ] **Step 1: Write API RED tests for bounded records and bound filters**

```python
def test_agent_page_flattens_one_large_turn_and_binds_filters(client) -> None:
    page = client.get('/api/runs/analysis-test/agent?kind=tool&capability=gridctl').json()
    assert page['items'][0]['kind'] == 'tool'
    assert page['items'][0]['parent_id']
    foreign = client.get('/api/runs/analysis-test/agent?kind=request&cursor=' + page['older_cursor'])
    assert foreign.status_code == 400

def test_context_and_evidence_pages_do_not_embed_documents_or_bytes(client) -> None:
    assert 'before_state' not in client.get('/api/runs/analysis-test/context').json()['items'][0]
    assert 'content' not in client.get('/api/runs/analysis-test/evidence').json()['items'][0]
```

- [ ] **Step 2: Run RED**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py -q`

Expected: FAIL because only whole-turn Agent pages, exact Context detail, and whole Evidence index exist.

- [ ] **Step 3: Add public page models and deterministic flatteners**

In `projection_pages.py`, flatten agent descendants in source-sequence order, create Context summaries without state documents, and map `ArtifactIndexRecord` to Evidence page records without adding bytes. Apply filters before creating `_ProjectionRecord`s. Canonicalize filters before creating the cursor expectation:

```python
filter_fingerprint = sha256(canonical_json_bytes(filters)).hexdigest()
expectation = CursorExpectation(
    analysis_id=projected.analysis_id,
    view=view,
    source_fingerprint=f'{projected.source_fingerprint}:{filter_fingerprint}',
    projection_version=_PROJECTION_VERSIONS[view],
)
```

Reject unsupported query values through `RequestValidationError`; never silently ignore a filter.

- [ ] **Step 4: Register typed endpoints**

Replace the current Agent page implementation, add cursor page mode to `/context` while preserving `at_sequence` detail, and make `/evidence` return pages. Route signatures must make page/detail unambiguous:

```python
def context_view(analysis_id: str, at_sequence: int | None = Query(default=None, ge=1), cursor: str | None = None, ...) -> dict[str, Any]:
    if at_sequence is not None: return _context_detail(...)
    return projection_page(..., 'context', cursor, filters, cursor_codec)
```

- [ ] **Step 5: Run GREEN and API security gates**

Run:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_projection_pages.py packages/grid-agent/tests/trajectory/api/test_app.py -q
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory/api packages/grid-agent/src/grid_agent/trajectory/projection_models.py
```

Expected: page records are bounded/public, filters bind cursors, detail remains exact, and GET-only errors retain security headers.

- [ ] **Step 6: Commit**

```sh
git add packages/grid-agent/src/grid_agent/trajectory/{api,projection_models.py} packages/grid-agent/tests/trajectory/api
git commit -m "feat: page trajectory operational projections"
```

### Task 2: Shared frontend operational paging controller

**Files:**
- Create: `packages/trajectory-workbench/src/api/operational-page.ts`
- Create: `packages/trajectory-workbench/src/api/operational-page.test.ts`
- Modify: `packages/trajectory-workbench/src/api/types.ts`
- Modify: `packages/trajectory-workbench/src/api/client.ts`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/state/workbench.ts`
- Test: `packages/trajectory-workbench/src/app/App.test.tsx`

**Interfaces:**

```ts
export interface PageRequest { cursor?: string; filters: Record<string, string | number | boolean | null>; }
export interface OperationalPageState<T> {
  items: T[]; page: ProjectionPage<T> | null;
  olderState: 'idle' | 'loading' | 'failed'; olderError: string | null;
  failedCursor: string | null; requestKey: string;
}
export function prependOperationalPage<T extends { id: string }>(older: T[], current: T[]): T[];
export function pageRequestKey(runId: string, view: WorkbenchView, request: PageRequest): string;
```

- [ ] **Step 1: Write stale/merge RED tests**

```ts
it('retains loaded rows and retries exactly the failed opaque cursor', () => {
  expect(prependOperationalPage([{ id: 'tool:1' }], [{ id: 'tool:1' }, { id: 'tool:2' }])).toEqual([{ id: 'tool:1' }, { id: 'tool:2' }]);
});

it('does not render a late Context page after the user selects another run', async () => {
  // resolve run A only after run B page resolves; assert only B rows appear
});
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/api/operational-page.test.ts src/app/App.test.tsx`

Expected: FAIL because non-Business views do not hold page/cursor state.

- [ ] **Step 3: Implement typed client endpoints and shared guards**

Add `getAgentPage`, `getContextPage`, and `getEvidencePage` request types. In `App`, capture `runId`, filters, cursor, and requested sequence before every fetch. The success handler must return without state mutation when either `signal.aborted` or the current request key differs:

```ts
if (controller.signal.aborted || currentRequestKeyRef.current !== requestKey || page.analysis_id !== runId) return;
```

Use stable-ID merge, clear a view's rows only for a new run/filter initial request, and preserve rows for older-page failures.

- [ ] **Step 4: Run GREEN and type gate**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/api/operational-page.test.ts src/api/client.test.ts src/app/App.test.tsx
npm run check --prefix packages/trajectory-workbench
```

Expected: exact cursor retry, stable merge, aborted/late response rejection, and strict API typing pass.

- [ ] **Step 5: Commit**

```sh
git add packages/trajectory-workbench/src/{api,app,state}
git commit -m "feat: share operational trajectory paging state"
```

### Task 3: Agent execution work surface

**Files:**
- Modify: `packages/trajectory-workbench/src/views/AgentView.tsx`
- Create: `packages/trajectory-workbench/src/views/AgentView.test.tsx`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Modify: `packages/trajectory-workbench/e2e/workbench.e2e.ts`

**Interfaces:**

```ts
interface AgentViewProps {
  rows: AgentEventRow[]; filters: AgentFilters; onFiltersChange(filters: AgentFilters): void;
  hasOlder: boolean; olderState: OlderState; olderError: string | null;
  onLoadOlder(): void; onRetryOlder(): void; onSelectNode(id: string): void;
  onSelectSequence(sequence: number): void;
}
```

- [ ] **Step 1: Write RED interaction tests**

```tsx
it('shows a truncated parent marker rather than inventing a missing tree parent', () => { /* page contains child only */ });
it('filters tool rows by capability, loads older rows, and retries the identical cursor', async () => { /* assert exact API arguments */ });
it('selects a tool and navigates only its recorded source sequence', () => { /* no nearest business relation */ });
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/views/AgentView.test.tsx src/app/App.test.tsx`

Expected: FAIL because Agent consumes whole nested turns and has no filter/paging controls.

- [ ] **Step 3: Render virtual flat hierarchy and explicit operations**

Render compact `treegrid` rows from typed parent/level fields; parent rows arriving later attach without changing IDs. Provide controls for turn, kind, status, capability, query, expand/collapse, Load older, and Retry. Request/response/tool rows show public title/status/sequence only. Tool selection calls `onSelectSequence(row.source_sequence)` and must expose an unavailable message when no recorded business relationship exists.

- [ ] **Step 4: Run GREEN and browser tree gate**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/views/AgentView.test.tsx src/app/App.test.tsx
npm run test:e2e --prefix packages/trajectory-workbench -- --grep 'agent operational paging|agent keyboard tree'
```

Expected: controls manipulate real API filters/cursors, tree keyboard navigation works, and mounted rows stay bounded.

- [ ] **Step 5: Commit**

```sh
git add packages/trajectory-workbench/src/views/AgentView.tsx packages/trajectory-workbench/src/views/AgentView.test.tsx packages/trajectory-workbench/src/app/App.tsx packages/trajectory-workbench/src/design/base.css packages/trajectory-workbench/e2e/workbench.e2e.ts
git commit -m "feat: operate paged agent trajectories"
```

### Task 4: Context replay and comparison work surface

**Files:**
- Create: `packages/trajectory-workbench/src/context/compare.ts`
- Create: `packages/trajectory-workbench/src/context/compare.test.ts`
- Modify: `packages/trajectory-workbench/src/views/ContextView.tsx`
- Modify: `packages/trajectory-workbench/src/views/ContextView.test.tsx`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Modify: `packages/trajectory-workbench/e2e/accessibility.e2e.ts`

**Interfaces:**

```ts
export interface ContextComparison { added: string[]; removed: string[]; changed: string[]; }
export function compareContextStates(left: JsonValue, right: JsonValue, prefix?: string): ContextComparison;
```

- [ ] **Step 1: Write RED tests**

```ts
it('compares only two fetched authoritative frame states', () => {
  expect(compareContextStates({ limits: { x: 1 } }, { limits: { x: 2 }, mode: 'n1' })).toEqual({ added: ['mode'], removed: [], changed: ['limits.x'] });
});

it('pages frame summaries and fetches detail only after selecting a frame', async () => { /* no before_state in page */ });
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/context/compare.test.ts src/views/ContextView.test.tsx src/app/App.test.tsx`

Expected: FAIL because Context only renders one frame and raw JSON tabs.

- [ ] **Step 3: Implement summary timeline, exact detail, and structured comparison**

Render virtual summary rows with filter controls and Load older/Retry. Selecting a row fetches `at_sequence`; previous/next choose only loaded summary sequences. Two pinned frame details feed `compareContextStates`; render added/removed/changed keys, never synthetic state. Replace primary raw `<pre>` blocks with collapsible structured nodes; retain a labelled secondary “Raw recorded JSON” disclosure. Request input continues through `artifactUrl` only when its verified ref is present.

- [ ] **Step 4: Run GREEN and accessibility gate**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/context/compare.test.ts src/views/ContextView.test.tsx src/app/App.test.tsx
npm run test:e2e --prefix packages/trajectory-workbench -- --grep 'context replay|context comparison'
```

Expected: filters/page/retry/detail/comparison work and tabs/controls are keyboard/Axe compliant.

- [ ] **Step 5: Commit**

```sh
git add packages/trajectory-workbench/src/context packages/trajectory-workbench/src/views/ContextView.tsx packages/trajectory-workbench/src/views/ContextView.test.tsx packages/trajectory-workbench/src/app/App.tsx packages/trajectory-workbench/src/design/base.css packages/trajectory-workbench/e2e/accessibility.e2e.ts
git commit -m "feat: replay and compare paged context frames"
```

### Task 5: Evidence investigation, safe preview, and release validation

**Files:**
- Create: `packages/trajectory-workbench/src/evidence/preview.ts`
- Create: `packages/trajectory-workbench/src/evidence/preview.test.ts`
- Modify: `packages/trajectory-workbench/src/views/EvidenceView.tsx`
- Modify: `packages/trajectory-workbench/src/views/DrilldownViews.test.tsx`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Modify: `packages/trajectory-workbench/e2e/fixtures.ts`
- Modify: `packages/trajectory-workbench/e2e/visual.e2e.ts`
- Modify: `packages/trajectory-workbench/e2e/accessibility.e2e.ts`
- Modify: `docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md`

**Interfaces:**

```ts
export interface ArtifactPreview { kind: 'json' | 'markdown' | 'text'; content: string; truncated: boolean; }
export async function loadSafePreview(url: string, fetcher: typeof fetch, maxBytes = 131_072): Promise<ArtifactPreview>;
```

Preview fetches an already-authorized artifact URL only, sends a `Range: bytes=0-131071` request when supported, and marks the result truncated at the bound. A record with `verification_status !== 'verified'` has neither preview nor download control.

- [ ] **Step 1: Write RED tests**

```tsx
it('disables preview and download for an unavailable evidence record with its reason', () => { /* assert no anchor */ });
it('filters verified evidence, previews bounded JSON, and jumps to its producer sequence', async () => { /* assert exact actions */ });
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/evidence/preview.test.ts src/views/DrilldownViews.test.tsx src/app/App.test.tsx`

Expected: FAIL because Evidence is an unpaged table with unconditional download anchors and no preview.

- [ ] **Step 3: Implement virtual investigation table and preview drawer**

Add kind/source/verification/sequence/relevance/sort controls. Render virtual rows with page status/range, safe preview drawer, copy-reference action, producer/consumer sequence buttons, and exact-cursor retry. The preview helper accepts only JSON/Markdown/text response content types and caps output. For unavailable records render the persisted reason and no actionable URL.

- [ ] **Step 4: Run GREEN and full release gates**

Run:

```sh
npm test --prefix packages/trajectory-workbench
npm run check --prefix packages/trajectory-workbench
npm run test:e2e --prefix packages/trajectory-workbench
npm run test:visual --prefix packages/trajectory-workbench
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api packages/grid-agent/tests/trajectory/projections -q
make test
make test-e2e
make validate
```

Verify a native and `runs/analysis-20260814T081822Z` legacy run on a fresh loopback server: every Agent/Context/Evidence page loads, filters, pages, retries a fixture failure, selection synchronizes Inspector, verified preview/download works, and unavailable records remain blocked.

- [ ] **Step 5: Update the operator guide and commit**

Document each view's filters, Load older/Retry behavior, Context comparison, Evidence preview limits, native/legacy availability semantics, and the validation commands.

```sh
git add packages/trajectory-workbench docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md
git commit -m "feat: operate paged trajectory evidence and context"
```

## Plan Self-Review

- **Spec coverage:** Task 1 supplies filter-bound backend pages; Task 2 supplies shared client cursor/stale-state semantics; Tasks 3–5 provide the complete Agent, Context, and Evidence operations; Task 5 validates native/legacy, visual, accessibility, and full release gates.
- **No placeholders:** Every functional change names concrete paths, data contracts, RED commands, implementation behavior, and GREEN commands.
- **Type consistency:** `ProjectionPage<T>`, `PageRequest`, `OperationalPageState<T>`, `AgentEventRow`, `ContextFrameSummary`, and `ArtifactPreview` are defined before their consumer tasks; selected details continue to use exact IDs/sequences.
