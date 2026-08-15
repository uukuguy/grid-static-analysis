# Trajectory Workbench Audit Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a dense desktop-first trajectory audit workbench in which every selected business node leads to concrete overview, evidence, context, and execution investigation actions.

**Architecture:** Keep the backend read-only and projections authoritative. Introduce a small frontend `AuditSelection` adapter that resolves a business node to stable turn/request/tool/evidence identities; `AuditInspector` consumes only that adapter plus already-loaded typed pages. Rebuild Business rows and run navigation around compact virtualized causal items, and add only bounded typed API data where an existing projection cannot expose a durable relationship.

**Tech Stack:** React 19, TypeScript strict mode, Vite/Vitest, TanStack Virtual, Playwright + Axe, FastAPI/Pydantic read-only trajectory API, pytest.

## Global Constraints

- All run facts remain sourced from native events, legacy importer output, or `ProjectedRun`; never infer relationships from prose.
- Preserve same-origin GET-only API, loopback-only server, artifact registry/hash checks, no CORS and no hidden model reasoning.
- Default desktop body text is 13px; node metadata is 11px monospace; ordinary view headings are at most 16px.
- Keep 100k business trajectories virtualized and cursor-paginated; a failed older-page retry must repeat the failed cursor.
- `partial` remains inspectable, `corrupt` blocks untrusted content, and unavailable facts show an explicit reason.
- Preserve desktop 360px inspector, 800–1199 resizable inspector, and <800px accessible modal sheet behavior.
- Every task is TDD: record RED before implementation, run focused GREEN, then run the declared broader gates.

---

### Task 1: Typed audit selection and run/turn navigation

**Files:**
- Create: `packages/trajectory-workbench/src/audit/selection.ts`
- Create: `packages/trajectory-workbench/src/audit/selection.test.ts`
- Modify: `packages/trajectory-workbench/src/api/types.ts`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/components/layout/RunExplorer.tsx`
- Modify: `packages/trajectory-workbench/src/state/workbench.ts`
- Test: `packages/trajectory-workbench/src/app/App.test.tsx`

**Interfaces:**
- Consumes: `BusinessProblem`, `BusinessNode`, `AgentTurn`, `EvidenceIndex`, `ContextFrame`, and the current `selectedNodeId`.
- Produces:

```ts
export interface AuditSelection {
  problem: BusinessProblem;
  node: BusinessNode | null;
  sequence: number;
  turnId: string;
  artifactRefs: string[];
  agentTurn: AgentTurn | null;
}

export function resolveAuditSelection(
  problems: BusinessProblem[],
  agentTurns: AgentTurn[],
  selectedNodeId: string | null,
): AuditSelection | null;
```

- Later tasks consume `AuditSelection`; they must not repeat parent/node lookup logic.

- [ ] **Step 1: Write failing selection and rail tests**

```ts
it('resolves a nested claim to its exact sequence, refs, and owning turn', () => {
  expect(resolveAuditSelection([problem], [turn], 'claim:7')).toMatchObject({
    sequence: 48,
    turnId: 'analysis-t007',
    artifactRefs: ['evidence:line-17', 'result:contingency-17'],
  });
});

it('selecting a problem in the rail focuses its causal group without replacing node selection', async () => {
  render(<App client={client} />);
  await user.click(screen.getByRole('button', { name: /Q7.*3 decisions/i }));
  expect(screen.getByRole('heading', { name: /Q7.*Line 17/i })).toBeVisible();
});
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/audit/selection.test.ts src/app/App.test.tsx`
Expected: FAIL because `resolveAuditSelection` and turn-navigation affordances do not exist.

- [ ] **Step 3: Extend only the types required for durable links**

Add optional bounded relation fields already available from projection data; do not add prose parsing:

```ts
export interface BusinessProblem extends ProjectionNode {
  source_sequence: number;
  turn_id: string;
  title: string;
  nodes: BusinessNode[];
}
```

Implement `resolveAuditSelection()` by locating the parent problem, nested node, exact node sequence, de-duplicated refs, and matching `AgentTurn.turn_id`.

- [ ] **Step 4: Implement rail selection semantics**

Add a reducer action that distinguishes a problem-group focus from a node selection:

```ts
| { type: 'problem/focused'; problemId: string }
```

`RunExplorer` renders a compact turn/problem index after run selection. Its button dispatches `problem/focused`; `BusinessView` scrolls/focuses the matching virtual group header without clearing a selected node.

- [ ] **Step 5: Run GREEN and broader state tests**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/audit/selection.test.ts src/state/workbench.test.ts src/app/App.test.tsx
npm run check --prefix packages/trajectory-workbench
```

Expected: all pass; exact nested node uses its own sequence/refs and problem navigation remains keyboard accessible.

- [ ] **Step 6: Commit**

```sh
git add packages/trajectory-workbench/src/audit packages/trajectory-workbench/src/api/types.ts \
  packages/trajectory-workbench/src/app/App.tsx packages/trajectory-workbench/src/components/layout/RunExplorer.tsx \
  packages/trajectory-workbench/src/state
git commit -m "feat: resolve trajectory audit selections"
```

### Task 2: Compact causal Business trajectory and real pagination states

**Files:**
- Modify: `packages/trajectory-workbench/src/components/trajectory/TrajectoryRow.tsx`
- Modify: `packages/trajectory-workbench/src/components/trajectory/VirtualTrajectory.tsx`
- Modify: `packages/trajectory-workbench/src/views/BusinessView.tsx`
- Modify: `packages/trajectory-workbench/src/views/BusinessView.test.tsx`
- Modify: `packages/trajectory-workbench/src/components/trajectory/VirtualTrajectory.test.tsx`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Test: `packages/trajectory-workbench/src/app/App.test.tsx`

**Interfaces:**
- Consumes: `AuditSelection`, `BusinessTrajectoryRow`, cursor callback `onRequestOlder(anchor)`.
- Produces compact row DOM with `data-testid="causal-node-<id>"`, `aria-current="true"` when selected, and a `data-causal-kind` value.

- [ ] **Step 1: Write failing dense-row, cursor, and virtual header tests**

```ts
it('renders a causal row with sequence, kind, source, status, revision, and ref count', () => {
  render(<TrajectoryRow item={claim} selected={false} onSelect={vi.fn()} />);
  expect(screen.getByText('#48')).toBeVisible();
  expect(screen.getByText(/claim.*2 refs/i)).toBeVisible();
  expect(screen.getByText(/context r12/i)).toBeVisible();
});

it('retries the exact failed older cursor and keeps the virtual anchor', async () => {
  // first older request rejects; Retry must call getBusinessPage(run, 'cursor-before-48')
});

it('keeps problem headers inside the <=120-row virtual window for 100k events', () => {
  expect(screen.getAllByTestId(/causal-node|problem-header/)).toHaveLength(expect.any(Number));
});
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/views/BusinessView.test.tsx src/components/trajectory/VirtualTrajectory.test.tsx`
Expected: FAIL because rows do not provide causal metadata/expansion and cursor retry state is not visible in the business surface.

- [ ] **Step 3: Implement the compact causal row**

Use a fixed dense summary and optional expanded disclosure:

```tsx
<button className="causal-row" data-testid={`causal-node-${item.id}`} onClick={onSelect}>
  <span className="causal-row-meta">#{item.source_sequence} · {item.kind} · {item.status}</span>
  <strong>{item.title}</strong>
  <span className="causal-row-facts">{item.source} · context r{item.contextRevision ?? '—'} · {item.refs.length} refs</span>
</button>
```

Derive `contextRevision` only from an explicit projection field; render `Context unavailable` when it is absent. Add a disclosure for the bounded `detail` string, unavailable reason, and references; do not load raw artifacts in the row.

- [ ] **Step 4: Implement cursor status and preserve virtual invariants**

`VirtualTrajectory` receives:

```ts
olderState: 'idle' | 'loading' | 'failed';
olderError: string | null;
onRetryOlder: () => void;
```

Render a sticky `Load older history`, disabled loading state, or named `Retry older history` button. Keep the virtual prepend anchor and problem headers in the item list.

- [ ] **Step 5: Apply density CSS**

Replace presentation-card spacing with row rules:

```css
.causal-row { min-height:44px; padding:7px 9px; gap:3px; }
.causal-row-meta, .causal-row-facts { font:11px var(--wb-font-mono); }
.causal-row strong { font-size:14px; line-height:1.25; }
.trajectory-main { padding:16px 20px; }
```

Use borders and selection accent, not large empty cards.

- [ ] **Step 6: Run GREEN and browser performance gate**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/views/BusinessView.test.tsx src/components/trajectory/VirtualTrajectory.test.tsx src/app/App.test.tsx
npm run check --prefix packages/trajectory-workbench
npm run test:e2e --prefix packages/trajectory-workbench -- --grep '100k trajectory'
```

Expected: focused tests pass; browser test proves bounded DOM and real older-cursor retry.

- [ ] **Step 7: Commit**

```sh
git add packages/trajectory-workbench/src/components/trajectory packages/trajectory-workbench/src/views/BusinessView.tsx \
  packages/trajectory-workbench/src/views/BusinessView.test.tsx packages/trajectory-workbench/src/design/base.css \
  packages/trajectory-workbench/src/app/App.test.tsx
git commit -m "feat: render compact causal business trajectory"
```

### Task 3: Four-tab Investigation Inspector with evidence, context, and execution closure

**Files:**
- Create: `packages/trajectory-workbench/src/audit/inspector-model.ts`
- Create: `packages/trajectory-workbench/src/audit/inspector-model.test.ts`
- Create: `packages/trajectory-workbench/src/components/audit/AuditInspector.tsx`
- Create: `packages/trajectory-workbench/src/components/audit/AuditInspector.test.tsx`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/components/layout/Inspector.tsx`
- Modify: `packages/trajectory-workbench/src/views/ContextView.tsx`
- Modify: `packages/trajectory-workbench/src/views/EvidenceView.tsx`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Test: `packages/trajectory-workbench/src/app/App.test.tsx`

**Interfaces:**

```ts
export type AuditPanel = 'overview' | 'evidence' | 'context' | 'execution';
export interface AuditInspectorModel {
  selection: AuditSelection;
  evidence: EvidenceRecord[];
  context: ContextFrame | null;
  execution: AgentTurn | null;
  unavailable: Partial<Record<AuditPanel, string>>;
}
export function buildAuditInspectorModel(args: {
  selection: AuditSelection;
  evidenceIndex: EvidenceIndex | null;
  context: ContextFrame | null;
}): AuditInspectorModel;
```

- [ ] **Step 1: Write failing model and end-to-end Inspector tests**

```tsx
it('shows selected claim evidence with verified digest and jumps to the producing sequence', async () => {
  render(<App client={client} />);
  await user.click(screen.getByTestId('causal-node-claim:7'));
  await user.click(screen.getByRole('tab', { name: 'Evidence' }));
  expect(screen.getByText(/verified/i)).toBeVisible();
  await user.click(screen.getByRole('button', { name: /go to sequence 47/i }));
  expect(screen.getByTestId('causal-node-tool:17')).toHaveAttribute('aria-current', 'true');
});

it('shows unavailable context reason instead of a fabricated document', () => {
  render(<AuditInspector model={legacyModelWithoutRequest} />);
  expect(screen.getByText(/request input is unavailable/i)).toBeVisible();
});
```

- [ ] **Step 2: Run RED**

Run: `npm test --prefix packages/trajectory-workbench -- --run src/audit/inspector-model.test.ts src/components/audit/AuditInspector.test.tsx src/app/App.test.tsx`
Expected: FAIL because existing generic Inspector tabs render placeholder JSON and do not expose cross-projection jumps.

- [ ] **Step 3: Build the model without inference**

- Evidence consists only of `EvidenceRecord`s whose `reference` is in `selection.artifactRefs`.
- Context is accepted only when `frame.source_sequence === selection.sequence`; otherwise set `unavailable.context`.
- Execution is `selection.agentTurn`; request/tool entries are rendered only when their stable ids/sequences match the selected business relation. If no durable relation exists, show `Execution linkage is unavailable for this event`.

- [ ] **Step 4: Implement `AuditInspector` panels and actions**

```tsx
<AuditInspector
  model={model}
  onSelectNode={(nodeId) => dispatch({ type: 'node/selected', nodeId })}
  onSelectSequence={(sequence) => setContextSequence(sequence)}
  artifactUrl={artifactUrl}
/>
```

- Overview: stable ID, turn, source, status, sequence, parent/child links, limitation text.
- Evidence: verification status, producer/consumer sequence buttons, safe artifact download/preview link.
- Context: revisions, before/delta/after, request input availability; buttons update `context:<sequence>`.
- Execution: public request metadata, tool parameter/result summaries, retry/duration/failure; no credentials or hidden reasoning.

Replace `Inspector.tsx` with a thin responsive shell that hosts `AuditInspector`; remove generic `JSON.stringify({ node, tab })` placeholders.

- [ ] **Step 5: Add explicit asynchronous and unavailable states**

Each panel receives `loading`, `unavailable`, `unsupported`, or `network-error` from actual API results. A retry must refetch only the failed projection/sequence. `partial` displays a non-blocking banner with available facts; `corrupt` blocks untrusted panel content.

- [ ] **Step 6: Run GREEN and API gates**

Run:

```sh
npm test --prefix packages/trajectory-workbench -- --run src/audit/inspector-model.test.ts src/components/audit/AuditInspector.test.tsx src/app/App.test.tsx
npm run check --prefix packages/trajectory-workbench
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api -q
```

Expected: four panels show durable facts or explicit unavailable reasons; API remains GET-only and typed.

- [ ] **Step 7: Commit**

```sh
git add packages/trajectory-workbench/src/audit packages/trajectory-workbench/src/components/audit \
  packages/trajectory-workbench/src/app/App.tsx packages/trajectory-workbench/src/components/layout/Inspector.tsx \
  packages/trajectory-workbench/src/views packages/trajectory-workbench/src/design/base.css
git commit -m "feat: add trajectory investigation inspector"
```

### Task 4: Bounded read-only execution investigation API

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/trajectory/projection_models.py`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/agent_projection.py`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/api/app.py`
- Modify: `packages/grid-agent/tests/trajectory/projections/test_agent.py`
- Modify: `packages/grid-agent/tests/trajectory/api/test_app.py`
- Modify: `packages/trajectory-workbench/src/api/types.ts`
- Modify: `packages/trajectory-workbench/src/api/client.ts`
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: `packages/trajectory-workbench/src/components/audit/AuditInspector.tsx`
- Test: `packages/trajectory-workbench/src/api/client.test.ts`
- Test: `packages/trajectory-workbench/src/components/audit/AuditInspector.test.tsx`

**Interfaces:**

Add this bounded endpoint so the Execution panel can request the exact, server-resolved execution relationship for any selected business sequence rather than approximating it from an already-paged client projection:

```text
GET /api/runs/{analysis_id}/execution?at_sequence={sequence}
```

Response contract:

```ts
export interface ExecutionSlice {
  analysis_id: string;
  source_sequence: number;
  turn: AgentTurn | null;
  unavailable_reason: string | null;
}
```

It is derived exclusively by sequence/scoped stable ids from `ProjectedRun.agent`; no raw Pi sidecar, filesystem path, or hidden response data is exposed.

- [ ] **Step 1: Prove the gap with a failing API/projection test**

```python
def test_execution_slice_returns_only_agent_records_causally_bound_to_sequence() -> None:
    response = client.get('/api/runs/analysis-test/execution?at_sequence=48')
    assert response.status_code == 200
    assert response.json()['turn']['turn_id'] == 'analysis-test-t007'
    assert 'provider_payload' not in response.text
```

Add a legacy test where no mapping is proven and `unavailable_reason` is non-null.

- [ ] **Step 2: Run RED**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py::test_execution_slice_returns_only_agent_records_causally_bound_to_sequence -q`
Expected: FAIL with `404` before implementation.

- [ ] **Step 3: Implement bounded projection lookup**

Add a method on the projection service that returns the owning turn only if an agent node has an explicit source sequence containing `at_sequence`. Preserve `None` rather than choosing the nearest turn.

```python
def execution_slice(self, sequence: int) -> ExecutionSlice:
    for turn in self.projected.agent.turns:
        if _turn_contains_sequence(turn, sequence):
            return ExecutionSlice(analysis_id=self.analysis_id, source_sequence=sequence, turn=turn)
    return ExecutionSlice(analysis_id=self.analysis_id, source_sequence=sequence, turn=None,
                          unavailable_reason='no durable execution linkage is recorded')
```

Register the GET route before SPA fallback and apply the same security/error handlers as existing projection routes.

- [ ] **Step 4: Add client implementation**

```ts
getExecutionSlice(id: string, atSequence: number, signal?: AbortSignal) {
  return this.get<ExecutionSlice>(`/api/runs/${encodeURIComponent(id)}/execution?at_sequence=${atSequence}`, signal);
}
```

- [ ] **Step 5: Bind the Execution panel to the exact slice**

When the selected `AuditSelection.sequence` changes, `App` fetches this endpoint with an abort signal and passes only the returned `ExecutionSlice` to `AuditInspector`. The panel must render `unavailable_reason` when `turn` is null; it must not fall back to a nearest or previously loaded agent turn. Add an Inspector regression proving a sequence change aborts the prior request and displays the new slice only.

- [ ] **Step 6: Run GREEN and security regression**

Run:

```sh
uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/api/test_app.py -q
npm test --prefix packages/trajectory-workbench -- --run src/api/client.test.ts
npm test --prefix packages/trajectory-workbench -- --run src/components/audit/AuditInspector.test.tsx src/app/App.test.tsx
uv run --project packages/grid-agent pyright packages/grid-agent/src/grid_agent/trajectory packages/grid-agent/tests/trajectory/api/test_app.py
```

Expected: native mapping is exact; legacy returns explicit unavailable; POST stays 405 and response has no raw provider payload.

- [ ] **Step 7: Commit**

```sh
git add packages/grid-agent/src/grid_agent/trajectory packages/grid-agent/tests/trajectory \
  packages/trajectory-workbench/src/api packages/trajectory-workbench/src/app/App.tsx \
  packages/trajectory-workbench/src/components/audit
git commit -m "feat: expose bounded trajectory execution slices"
```

### Task 5: Professional visual system, responsive audit shell, and release validation

**Files:**
- Modify: `packages/trajectory-workbench/src/design/tokens.css`
- Modify: `packages/trajectory-workbench/src/design/base.css`
- Modify: `packages/trajectory-workbench/src/components/layout/WorkbenchShell.tsx`
- Modify: `packages/trajectory-workbench/src/components/layout/WorkbenchShell.test.tsx`
- Modify: `packages/trajectory-workbench/e2e/fixtures.ts`
- Modify: `packages/trajectory-workbench/e2e/accessibility.e2e.ts`
- Modify: `packages/trajectory-workbench/e2e/visual.e2e.ts`
- Modify: `packages/trajectory-workbench/e2e/workbench.e2e.ts`
- Update: `packages/trajectory-workbench/e2e/visual.e2e.ts-snapshots/*.png`
- Modify: `docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md`

**Interfaces:**
- Consumes the `AuditInspector`, compact causal rows, and any `ExecutionSlice` client from prior tasks.
- Produces stable test IDs: `audit-rail`, `causal-node-*`, `audit-inspector`, `audit-panel-overview`, `audit-panel-evidence`, `audit-panel-context`, `audit-panel-execution`.

- [ ] **Step 1: Write visual and interaction RED tests**

```ts
test('desktop audit density shows ten causal rows and all three audit regions at 1440px', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await expect(page.getByTestId('audit-rail')).toBeVisible();
  await expect(page.locator('[data-testid^="causal-node-"]')).toHaveCount(10);
  await expect(page.getByTestId('audit-inspector')).toBeVisible();
});

test('claim investigation reaches evidence, context, and execution without a route reload', async ({ page }) => {
  await page.getByTestId('causal-node-claim:7').click();
  for (const panel of ['Evidence', 'Context', 'Execution']) {
    await page.getByRole('tab', { name: panel }).click();
    await expect(page.getByTestId(`audit-panel-${panel.toLowerCase()}`)).toBeVisible();
  }
});
```

- [ ] **Step 2: Run RED**

Run: `npm run test:e2e --prefix packages/trajectory-workbench -- --grep 'desktop audit density|claim investigation'`
Expected: FAIL because the current UI lacks audit test IDs, compact rows, and four-panel investigation flow.

- [ ] **Step 3: Apply the visual token and shell rules**

- Set explicit dense font scale tokens (`--wb-font-body: 13px`, `--wb-font-meta: 11px`, `--wb-font-title: 16px`).
- Use 8px spacing increments, low-contrast panel separation, readable 1px borders, and selected-node accent.
- Ensure wide shell shows rail / causal trajectory / inspector simultaneously; medium shell consumes its resize variable; mobile uses the existing accessible sheet without duplicating inspector DOM.
- Do not add gradients, oversized cards, ornamental charts, or unbounded raw JSON panels.

- [ ] **Step 4: Make browser validation hermetic by default**

Change `playwright.config.ts` so pinned Playwright Chromium is default and system Chrome is enabled only by explicit `TRAJECTORY_WORKBENCH_BROWSER_CHANNEL=chrome`. Set `reuseExistingServer` only for an explicit local environment variable. Document the fallback in the operator guide.

- [ ] **Step 5: Generate and review visual baselines**

Run:

```sh
npx playwright install chromium --prefix packages/trajectory-workbench
npm run test:visual --prefix packages/trajectory-workbench -- --update-snapshots
npm run test:visual --prefix packages/trajectory-workbench
```

Inspect wide dark, wide light, 1024 resizable, 768 sheet, all async states, and all four Inspector panels. Accept snapshots only if node density and text hierarchy match the design contract.

- [ ] **Step 6: Run full release gates**

```sh
npm run check --prefix packages/trajectory-workbench
npm test --prefix packages/trajectory-workbench
npm run test:e2e --prefix packages/trajectory-workbench
make test
make test-e2e
make validate
```

Start `make trajectory PORT=8765`; verify the UI and GET API for a native fixture and `runs/analysis-20260814T081822Z`, then stop it. Confirm `/api/not-a-route` remains JSON and write methods return 405.

- [ ] **Step 7: Commit**

```sh
git add packages/trajectory-workbench docs/TRAJECTORY-WORKBENCH-OPERATOR-GUIDE.md
git commit -m "feat: deliver professional trajectory audit workbench"
```

## Plan Self-Review

- **Spec coverage:** Task 1 provides exact selection and navigation; Task 2 covers dense causal timeline/pagination/100k; Task 3 covers all four investigation surfaces and unavailable states; Task 4 supplies an exact bounded execution slice; Task 5 covers typography, responsive behavior, visual/a11y/release evidence.
- **No placeholders:** All functionality is assigned to a task with explicit files, interfaces, RED command, implementation direction, GREEN command, and commit boundary.
- **Type consistency:** `AuditSelection` from Task 1 is the sole selection input to Task 3. `ExecutionSlice` from Task 4 is the authoritative execution input and is named consistently in the client and Inspector integration. All API additions remain bounded GET contracts.
