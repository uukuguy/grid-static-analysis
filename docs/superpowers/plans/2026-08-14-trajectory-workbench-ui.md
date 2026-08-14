# Trajectory Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a polished business-first local Web workbench for Agent, Business, Context, and Evidence trajectories at or above DeepSeek Harness's information density, interaction quality, accessibility, and visual finish.

**Architecture:** A React/TypeScript single-page app consumes only the read-only API. Project-owned design tokens and focused components implement the four-region shell, while TanStack Virtual provides headless long-list measurement with stable source-sequence keys. One reducer owns selected run/view/node, page prepend anchors, filters, folds, timeline focus, theme, and inspector state so interactions remain deterministic across pagination.

**Tech Stack:** Node.js 22.19+, React 19.2, React DOM 19.2, TypeScript 7, Vite 8, TanStack React Virtual 3.14, Vitest 4.1, React Testing Library 16.3, Playwright 1.62, axe-core Playwright 4.12, CSS custom properties, SVG.

## Global Constraints

- The approved visual baseline is `docs/superpowers/mockups/2026-08-14-trajectory-workbench.html`.
- Business is the default view; Agent, Context, and Evidence are drill-down tabs.
- Persistent regions are left run explorer, top run header/timeline, center view, and right inspector.
- UI source labels are always textual/iconographic (`Observed`, `Derived`, `Agent-declared`) and never color-only.
- The browser never receives credentials, process environments, raw Pi sidecars, or unregistered files.
- The browser cannot invoke grid tools, mutate runs, edit evidence, or control an active agent.
- No hidden chain-of-thought is rendered; only public assistant output, declared decisions/claims, tool behavior, retries, timing, usage, context, and evidence appear.
- Lists use stable semantic IDs/source sequences, sequence cursors, virtualized DOM, and bounded overscan.
- Initial load opens the current tail; older history prepends without changing selection, focus, or the visible anchor.
- Every async surface has loading, empty, partial, corrupt, unsupported, and retryable-network states.
- Keyboard operation, visible focus, ARIA semantics, reduced motion, dark/light themes, and responsive inspector behavior are release gates.
- A synthetic 100,000-event fixture must remain paginated and mount no more than 120 trajectory rows at once.
- Static production assets use no inline script/style so API CSP remains `self`-only.
- Use red/green TDD, focused tests first, screenshot review, and one atomic commit per task.

## File Map

### New frontend package

- `packages/trajectory-workbench/package.json` and `package-lock.json` — locked frontend dependencies/scripts.
- `packages/trajectory-workbench/tsconfig.json`, `tsconfig.app.json`, `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts` — build/test configuration.
- `packages/trajectory-workbench/index.html` — CSP-compatible SPA document.
- `packages/trajectory-workbench/src/main.tsx` — React root.
- `packages/trajectory-workbench/src/app/App.tsx` — data loading and view composition.
- `packages/trajectory-workbench/src/api/types.ts` — exact API contracts.
- `packages/trajectory-workbench/src/api/client.ts` — abortable same-origin read-only client.
- `packages/trajectory-workbench/src/state/workbench.ts` — reducer/actions/selectors.
- `packages/trajectory-workbench/src/design/tokens.css` — dark/light type, spacing, color, elevation, motion tokens.
- `packages/trajectory-workbench/src/design/base.css` — reset, focus, typography, and shared primitives.
- `packages/trajectory-workbench/src/components/layout/WorkbenchShell.tsx`
- `packages/trajectory-workbench/src/components/layout/RunExplorer.tsx`
- `packages/trajectory-workbench/src/components/layout/RunHeader.tsx`
- `packages/trajectory-workbench/src/components/layout/OverviewTimeline.tsx`
- `packages/trajectory-workbench/src/components/layout/Inspector.tsx`
- `packages/trajectory-workbench/src/components/common/AsyncState.tsx`
- `packages/trajectory-workbench/src/components/common/SourceBadge.tsx`
- `packages/trajectory-workbench/src/components/common/Icon.tsx`
- `packages/trajectory-workbench/src/components/trajectory/VirtualTrajectory.tsx`
- `packages/trajectory-workbench/src/components/trajectory/TrajectoryRow.tsx`
- `packages/trajectory-workbench/src/views/BusinessView.tsx`
- `packages/trajectory-workbench/src/views/AgentView.tsx`
- `packages/trajectory-workbench/src/views/ContextView.tsx`
- `packages/trajectory-workbench/src/views/EvidenceView.tsx`
- `packages/trajectory-workbench/src/test/fixtures.ts` — native, legacy, partial, corrupt, and 100k fixtures.
- `packages/trajectory-workbench/src/**/*.test.tsx` — unit/component tests colocated by responsibility.
- `packages/trajectory-workbench/e2e/workbench.spec.ts`
- `packages/trajectory-workbench/e2e/accessibility.spec.ts`
- `packages/trajectory-workbench/e2e/visual.spec.ts`
- `packages/trajectory-workbench/e2e/visual.spec.ts-snapshots/*` — approved screenshot baselines.

### Modified backend/build files

- `packages/grid-agent/src/grid_agent/trajectory/api/app.py` — serve built SPA and assets after `/api` routes.
- `packages/grid-agent/src/grid_agent/trajectory/api/models.py` — generated-contract export fixture if type drift is detected.
- `packages/grid-agent/pyproject.toml` — include `trajectory/static/**` in wheel.
- `packages/grid-agent/src/grid_agent/trajectory/static/*` — deterministic Vite production output.
- `Makefile` — setup/test/build/serve targets.
- `.gitignore` — ignore transient Vite/Playwright output but not production static assets or screenshot baselines.
- `docs/RUNBOOK.md` and `docs/MANUAL-VALIDATION.md` — Workbench operation and visual acceptance.

---

### Task 1: Frontend foundation, exact API types, and design tokens

**Files:**
- Create: package/config files, `index.html`, `src/main.tsx`, `src/app/App.tsx`, `src/api/types.ts`, `src/api/client.ts`, `src/state/workbench.ts`, `src/design/tokens.css`, `src/design/base.css`, and foundation tests.

**Interfaces:**
- Produces: `TrajectoryApiClient` methods `listRuns`, `getRun`, `getBusinessPage`, `getAgentPage`, `getContextFrame`, and `artifactUrl`.
- Produces state `WorkbenchState` and `workbenchReducer(state, action)`.
- Tabs are `type WorkbenchView = "business" | "agent" | "context" | "evidence"`; initial view is `business`.
- API requests are same-origin GET with `Accept: application/json`, `AbortSignal`, and typed `ApiError`.

- [ ] **Step 1: Create package manifest and failing foundation tests**

```json
{
  "name": "@grid-static-analysis/trajectory-workbench",
  "version": "0.2.0",
  "private": true,
  "type": "module",
  "engines": { "node": ">=22.19.0" },
  "scripts": {
    "check": "tsc -b --pretty false",
    "build": "tsc -b --pretty false && vite build",
    "test": "vitest run",
    "test:e2e": "playwright test",
    "test:visual": "playwright test e2e/visual.spec.ts"
  },
  "dependencies": {
    "@tanstack/react-virtual": "^3.14.9",
    "react": "^19.2.8",
    "react-dom": "^19.2.8"
  },
  "devDependencies": {
    "@axe-core/playwright": "^4.12.1",
    "@playwright/test": "^1.62.0",
    "@testing-library/dom": "^10.4.1",
    "@testing-library/jest-dom": "^6.9.1",
    "@testing-library/react": "^16.3.2",
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "@vitejs/plugin-react": "^6.0.4",
    "jsdom": "^27.0.0",
    "typescript": "^7.0.2",
    "vite": "~8.1.5",
    "vitest": "^4.1.10"
  }
}
```

```tsx
it("starts in business view and retains selection across page prepend", () => {
  const selected: WorkbenchState = {
    ...initialWorkbenchState,
    selectedRunId: "analysis-test",
    selectedNodeId: "business:42",
    pages: { business: [tailPage] },
  };
  const next = workbenchReducer(selected, { type: "page/prepended", view: "business", page: olderPage });
  expect(next.activeView).toBe("business");
  expect(next.selectedNodeId).toBe("business:42");
  expect(next.pages.business.map((page) => page.firstSequence)).toEqual([1, 501]);
});


it("uses only same-origin GET requests", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
  const client = new TrajectoryApiClient(fetcher);
  await client.listRuns();
  expect(fetcher).toHaveBeenCalledWith("/api/runs", expect.objectContaining({ method: "GET" }));
  expect(fetcher.mock.calls[0][1].credentials).toBe("same-origin");
});
```

- [ ] **Step 2: Install and verify the tests fail**

Run: `npm install --prefix packages/trajectory-workbench && npm test --prefix packages/trajectory-workbench`

Expected: dependency lock is created; tests FAIL because API/state modules do not exist.

- [ ] **Step 3: Implement exact types, client, reducer, and tokens**

```ts
export type NodeSource = 'observed' | 'derived' | 'agent-declared';
export type LifecycleStatus = 'running' | 'completed' | 'failed' | 'interrupted' | 'unavailable';

export interface ProjectionPage<T> {
  items: T[];
  older_cursor: string | null;
  newer_cursor: null;
  first_sequence: number | null;
  last_sequence: number | null;
  has_older: boolean;
  encoded_bytes: number;
}

export interface BusinessNode {
  id: string;
  source_sequence: number;
  source: NodeSource;
  source_sequences: number[];
  rule_id: string | null;
  status: LifecycleStatus;
  kind: string;
  title: string;
  detail: string | null;
  refs: string[];
  unavailable_reason: string | null;
}
```

```ts
export class TrajectoryApiClient {
  constructor(private readonly fetcher: typeof fetch = fetch) {}

  private async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    if (!path.startsWith('/api/')) throw new Error('trajectory API path must be same-origin');
    const response = await this.fetcher(path, {
      method: 'GET', credentials: 'same-origin', headers: { Accept: 'application/json' }, signal,
    });
    if (!response.ok) throw await ApiError.fromResponse(response);
    return await response.json() as T;
  }

  listRuns(signal?: AbortSignal) { return this.get<RunListResponse>('/api/runs', signal); }
  getBusinessPage(id: string, cursor?: string, signal?: AbortSignal) {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
    return this.get<ProjectionPage<BusinessProblem>>(`/api/runs/${encodeURIComponent(id)}/business${query}`, signal);
  }
  artifactUrl(id: string, ref: string) {
    return `/api/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(ref)}`;
  }
}
```

Define every API response/error type from the backend Pydantic models, not a partial `Record<string, unknown>`. Reducer actions cover run/view selection, page requested/loaded/prepended/failed, node selection, fold toggle, search, timeline range, inspector open/close, theme, and prepend anchor. Tokens define the mockup's dark palette plus WCAG-checked light values, 4/8px spacing scale, 12px radius, sans/mono stacks, three elevation levels, 120/180ms motion, and reduced-motion overrides.

- [ ] **Step 4: Run foundation type/unit tests**

Run: `npm run check --prefix packages/trajectory-workbench && npm test --prefix packages/trajectory-workbench`

Expected: typecheck and all client/reducer/token contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench
git commit -m "feat: scaffold trajectory workbench"
```

### Task 2: Four-region shell, run explorer, timeline, and inspector

**Files:**
- Create: layout/common components and colocated tests listed in the File Map.
- Modify: `packages/trajectory-workbench/src/app/App.tsx`
- Modify: design CSS.

**Interfaces:**
- `WorkbenchShell` slots: `explorer`, `header`, `timeline`, `content`, `inspector`.
- `RunExplorer` emits `onSelectRun(analysisId)` and filter changes.
- `OverviewTimeline` emits `onFocusRange({startSequence, endSequence})` and `onSelectTurn(turnId)`.
- `Inspector` renders Identity, Input, Output, Timing, Context Delta, References, and Artifacts tabs for the selected node.

- [ ] **Step 1: Write failing shell interaction tests**

```tsx
it("renders the approved four-region hierarchy and business tab as selected", async () => {
  render(<App client={fixtureClient()} />);
  expect(await screen.findByRole('navigation', { name: 'Runs' })).toBeVisible();
  expect(screen.getByRole('region', { name: 'Run overview timeline' })).toBeVisible();
  expect(screen.getByRole('tab', { name: 'Business' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
});


it("selecting Q7 synchronizes timeline, content, and inspector", async () => {
  render(<App client={fixtureClient()} />);
  fireEvent.click(await screen.findByRole('button', { name: /Q7.*线路 17.*N-1/ }));
  expect(screen.getByRole('region', { name: 'Run overview timeline' })).toHaveAttribute('data-focused-turn', 'analysis-test-t007');
  expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('analysis-test-t007');
});


it("keyboard tabs move without a pointer", async () => {
  render(<App client={fixtureClient()} />);
  const business = await screen.findByRole('tab', { name: 'Business' });
  business.focus();
  fireEvent.keyDown(business, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: 'Agent' })).toHaveFocus();
});
```

- [ ] **Step 2: Run and confirm failures**

Run: `npm test --prefix packages/trajectory-workbench -- WorkbenchShell RunExplorer OverviewTimeline Inspector`

Expected: FAIL because shell components do not exist.

- [ ] **Step 3: Implement semantic shell and synchronized selection**

```tsx
export function WorkbenchShell({ explorer, header, timeline, content, inspector }: WorkbenchShellProps) {
  return (
    <div className="workbench-shell">
      <header className="topbar">{header}</header>
      <aside className="run-rail">{explorer}</aside>
      <section className="timeline-region" aria-label="Run overview timeline">{timeline}</section>
      <main className="trajectory-main">{content}</main>
      <aside className="inspector" aria-label="Trajectory inspector">{inspector}</aside>
    </div>
  );
}
```

```tsx
export function SourceBadge({ source }: { source: NodeSource }) {
  const labels = { observed: 'Observed', derived: 'Derived', 'agent-declared': 'Agent-declared' } as const;
  const icons = { observed: 'eye', derived: 'function', 'agent-declared': 'spark' } as const;
  return <span className={`source-badge source-${source}`}><Icon name={icons[source]} />{labels[source]}</span>;
}
```

Run explorer groups by completed/partial/corrupt and supports text/status/source-kind filters. Timeline uses one accessible SVG with turn segments, tool ticks, selection, focus range, and a text summary; it does not render one DOM node per event. Inspector uses tabs with roving focus and never injects raw HTML; JSON is rendered as escaped `<pre>` text and artifact links use `client.artifactUrl`.

- [ ] **Step 4: Run shell tests and a production build**

Run: `npm test --prefix packages/trajectory-workbench -- WorkbenchShell RunExplorer OverviewTimeline Inspector && npm run build --prefix packages/trajectory-workbench`

Expected: shell tests pass; Vite build succeeds without inline-script CSP warnings.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench/src
git commit -m "feat: build trajectory workbench shell"
```

### Task 3: Business-first virtual trajectory, pagination, search, and folding

**Files:**
- Create: `src/components/trajectory/VirtualTrajectory.tsx`, `TrajectoryRow.tsx`, tests.
- Create: `src/views/BusinessView.tsx`, test.
- Modify: `src/state/workbench.ts` and design CSS.

**Interfaces:**
- `VirtualTrajectory<T extends TrajectoryItem>` uses `getItemKey(index) => items[index].id`, `estimateSize`, dynamic `measureElement`, `overscan=8`, and `useFlushSync=false`.
- `onRequestOlder(cursor, anchor)` passes selected/first-visible semantic IDs and pixel offset; reducer restores them after prepend.
- `BusinessView` renders problems → nodes and supports source/status/text filters, per-problem fold, and timeline range.

- [ ] **Step 1: Write failing virtualization and prepend tests**

```tsx
it("mounts a bounded window for 100000 business nodes", async () => {
  render(<BusinessView problems={fixtureProblems(100_000)} state={initialViewState} dispatch={vi.fn()} />);
  await screen.findByRole('list', { name: 'Business trajectory' });
  const mountedItems = screen.getAllByRole('listitem');
  expect(mountedItems[0]).toHaveAttribute('aria-setsize', '100000');
  expect(mountedItems.length).toBeLessThanOrEqual(120);
});


it("uses semantic keys and preserves the visible anchor after prepend", async () => {
  const { rerender } = render(<VirtualTrajectory items={tailItems} onRequestOlder={requestOlder} renderRow={renderRow} />);
  scrollItemIntoView('business:750', 18);
  rerender(<VirtualTrajectory items={[...olderItems, ...tailItems]} onRequestOlder={requestOlder} renderRow={renderRow} />);
  expect(screen.getByTestId('business:750').getBoundingClientRect().top).toBeCloseTo(18, 1);
});


it("search and fold never remove the selected node from the inspector", () => {
  const state = stateWithSelectedNode('business:q7:claim');
  const searched = workbenchReducer(state, { type: 'search/changed', value: 'contingency' });
  const folded = workbenchReducer(searched, { type: 'problem/folded', problemId: 'q7', folded: true });
  expect(folded.selectedNodeId).toBe('business:q7:claim');
});
```

- [ ] **Step 2: Run and confirm failures**

Run: `npm test --prefix packages/trajectory-workbench -- VirtualTrajectory BusinessView workbench`

Expected: FAIL because virtual trajectory and business view do not exist.

- [ ] **Step 3: Implement virtual rows and anchor restoration**

```tsx
const virtualizer = useVirtualizer({
  count: items.length,
  getScrollElement: () => parentRef.current,
  estimateSize: index => estimateTrajectoryRow(items[index]),
  getItemKey: index => items[index].id,
  overscan: 8,
  useFlushSync: false,
});

return (
  <div ref={parentRef} className="virtual-scroll" onScroll={handleScroll}>
    <div role="list" aria-label={label} style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
      {virtualizer.getVirtualItems().map(row => (
        <div
          key={row.key}
          ref={virtualizer.measureElement}
          data-index={row.index}
          data-testid={items[row.index].id}
          role="listitem"
          aria-posinset={row.index + 1}
          aria-setsize={items.length}
          style={{ position: 'absolute', width: '100%', transform: `translateY(${row.start}px)` }}
        >
          {renderRow(items[row.index])}
        </div>
      ))}
    </div>
  </div>
);
```

Before requesting older data, store `virtualizer.getVirtualItems()[0]` semantic ID, its `start - scrollOffset`, focused element ID, and selection. After prepend, find the anchor's new index and call `scrollToOffset(measurements[index].start - savedOffset)`, then restore focus without scrolling. Business rows visually distinguish Problem header, Decision, Tool Action, Context Change, Claim, Answer/Evidence, Limitation, and Failure; each row contains source badge, sequence, title, bounded detail, status, semantic capability, refs count, and timing when known.

- [ ] **Step 4: Run business/virtualization tests**

Run: `npm test --prefix packages/trajectory-workbench -- VirtualTrajectory BusinessView workbench`

Expected: 100k DOM bound, stable keys, dynamic measurement, prepend anchor/focus/selection, pagination trigger, filters, search, folding, and unavailable-state tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench/src/components/trajectory packages/trajectory-workbench/src/views/BusinessView.tsx packages/trajectory-workbench/src/views/BusinessView.test.tsx packages/trajectory-workbench/src/state packages/trajectory-workbench/src/design
git commit -m "feat: render virtual business trajectories"
```

### Task 4: Agent, Context, and Evidence drill-down views

**Files:**
- Create: `src/views/AgentView.tsx`, `ContextView.tsx`, `EvidenceView.tsx` and tests.
- Modify: shared trajectory components, inspector, and CSS.

**Interfaces:**
- Agent view renders turn/step/request/retry/assistant/tool hierarchy with Input/Output/Timing/Schema/Artifact inspector tabs.
- Context view selects an event sequence and shows before/delta/after plus exact request input or explicit unavailable reason.
- Evidence view renders an accessible bidirectional tree/table for claims, decisions, results, evidence, scenarios, tools, and model revisions.

- [ ] **Step 1: Write failing view tests**

```tsx
it("agent view renders request timing retries and paired nested tools", () => {
  render(<AgentView trajectory={agentFixture()} state={viewState} dispatch={vi.fn()} />);
  expect(screen.getByText('Request 7.2')).toBeVisible();
  expect(screen.getByText(/TTFT 0.82 s/)).toBeVisible();
  expect(screen.getByText(/Retry 1 of 2/)).toBeVisible();
  expect(screen.getByRole('treeitem', { name: /analysis.contingency.n_minus_one.run.*completed/ })).toHaveAttribute('aria-level', '4');
});


it("context view shows exact before delta after and legacy unavailable input", () => {
  const { rerender } = render(<ContextView frame={nativeContextFrame()} onSelectSequence={vi.fn()} />);
  expect(screen.getByRole('tab', { name: 'Before' })).toBeVisible();
  expect(screen.getByText(REQUEST_INPUT_REF)).toBeVisible();
  rerender(<ContextView frame={legacyContextFrame()} onSelectSequence={vi.fn()} />);
  expect(screen.getByText('Legacy source did not capture model request input')).toBeVisible();
});


it("evidence relationships navigate in both directions", () => {
  render(<EvidenceView index={evidenceFixture()} selectedRef={Q7_EVIDENCE_REF} onSelectRef={selectRef} />);
  fireEvent.click(screen.getByRole('button', { name: /Claim.*N-1 校核不通过/ }));
  expect(selectRef).toHaveBeenCalledWith(Q7_CLAIM_REF);
  expect(screen.getByRole('treegrid')).toHaveAccessibleName('Evidence relationships');
});
```

- [ ] **Step 2: Run and confirm failures**

Run: `npm test --prefix packages/trajectory-workbench -- AgentView ContextView EvidenceView`

Expected: FAIL because the three views do not exist.

- [ ] **Step 3: Implement all drill-down views without prose inference**

```tsx
export function ContextView({ frame, onSelectSequence }: ContextViewProps) {
  return (
    <section aria-label="Context time travel" className="context-view">
      <SequenceScrubber value={frame.source_sequence} min={1} max={frame.max_sequence} onChange={onSelectSequence} />
      <Tabs labels={['Before', 'Delta', 'After']} panels={[
        <JsonDocument value={frame.before_state} />,
        <TypedDelta value={frame.delta} />,
        <JsonDocument value={frame.after_state} />,
      ]} />
      <section aria-label="Model-visible request input">
        {frame.request_artifact_ref
          ? <ArtifactLink reference={frame.request_artifact_ref} />
          : <Unavailable reason={frame.unavailable_reason ?? 'No following model request'} />}
      </section>
    </section>
  );
}
```

Agent tree items use stable lifecycle IDs, `aria-level`, `aria-expanded`, sequence, duration, TTFT, tokens, retry status, tool capability, arguments/result artifact links, and typed failures. Context state JSON remains collapsed by default with domain-aware summaries first. Evidence treegrid columns are relation, type, label, source, integrity, producing sequence, consumers, and artifact; arrow keys move rows and Enter selects. Never parse `answer_output` to add a relationship.

- [ ] **Step 4: Run focused view tests**

Run: `npm test --prefix packages/trajectory-workbench -- AgentView ContextView EvidenceView Inspector`

Expected: hierarchy, timing/usage, retry/interruption, time travel, request input, unavailable data, stale calculations, bidirectional relationships, and keyboard treegrid tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench/src/views packages/trajectory-workbench/src/components packages/trajectory-workbench/src/design
git commit -m "feat: add trajectory drill-down views"
```

### Task 5: Resilience, accessibility, themes, responsiveness, and visual baselines

**Files:**
- Create: `src/components/common/AsyncState.tsx` and test.
- Create: Playwright configs/specs and screenshot baselines.
- Modify: app/layout/views/design files.

**Interfaces:**
- Every resource state is `idle | loading | ready | empty | partial | corrupt | unsupported | network-error`.
- Theme follows `prefers-color-scheme` until explicitly toggled and persists only the UI preference in localStorage.
- Inspector is a 360px right panel ≥1200px, a 42vw resizable panel 800–1199px, and a modal bottom sheet <800px.
- Axe gate allows zero serious/critical violations on all four views and all non-ready states.

- [ ] **Step 1: Write Playwright resilience/a11y/visual tests**

```ts
test('all trajectory states remain useful and non-destructive', async ({ page }) => {
  for (const state of ['loading', 'empty', 'partial', 'corrupt', 'unsupported', 'network-error']) {
    await mockWorkbenchState(page, state);
    await page.goto('/');
    await expect(page.getByTestId(`state-${state}`)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete run' })).toHaveCount(0);
  }
});


test('business workbench has no serious accessibility violations', async ({ page }) => {
  await mockGoldenRun(page);
  await page.goto('/');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter(v => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([]);
});


test('approved wide dark workbench', async ({ page }) => {
  await mockGoldenRun(page);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: /Q7.*N-1/ }).click();
  await expect(page).toHaveScreenshot('business-q7-dark-wide.png', { animations: 'disabled', fullPage: true });
});
```

Add visual cases for light/wide, dark/1024px, narrow/768px bottom-sheet inspector, Agent retry, Context delta, Evidence tree, loading, partial, corrupt, and unsupported.

- [ ] **Step 2: Run and confirm failures**

Run: `npx playwright install chromium --with-deps && npm run test:e2e --prefix packages/trajectory-workbench`

Expected: component-state, accessibility, and visual tests FAIL because resilience layouts and baselines are missing.

- [ ] **Step 3: Implement resilient states and accessibility contracts**

```tsx
export function AsyncState({ state, diagnostic, onRetry, children }: AsyncStateProps) {
  if (state === 'ready') return <>{children}</>;
  const copy = STATE_COPY[state];
  return (
    <section className={`async-state state-${state}`} data-testid={`state-${state}`} role={state === 'network-error' ? 'alert' : 'status'}>
      <Icon name={copy.icon} />
      <h2>{copy.title}</h2>
      <p>{diagnostic ?? copy.detail}</p>
      {state === 'network-error' && <button type="button" onClick={onRetry}>Retry</button>}
    </section>
  );
}
```

Add skip link, semantic landmarks, roving tab/tree focus, visible 2px focus ring with 3:1 contrast, `aria-live="polite"` for page loads, `aria-busy`, source text labels, reduced-motion removal of scroll/transition animation, logical reading order, 44px minimum touch targets on narrow layouts, and inspector focus trap/return for bottom sheet. Implement both themes entirely through CSS variables and use no inline styles except dynamic numeric geometry required by virtualization/SVG.

- [ ] **Step 4: Review and approve screenshot baselines**

Run: `npm run test:visual --prefix packages/trajectory-workbench -- --update-snapshots && npm run test:e2e --prefix packages/trajectory-workbench`

Expected: inspect every generated screenshot against `docs/superpowers/mockups/2026-08-14-trajectory-workbench.html`; update snapshots only when hierarchy, density, typography, spacing, contrast, state clarity, and inspector behavior meet or exceed the mockup. Final E2E run passes with zero serious/critical axe violations.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench/src packages/trajectory-workbench/e2e packages/trajectory-workbench/playwright.config.ts packages/trajectory-workbench/e2e/visual.spec.ts-snapshots
git commit -m "test: lock workbench visual quality"
```

### Task 6: Production assets, backend SPA serving, and Make workflow

**Files:**
- Modify: `packages/trajectory-workbench/vite.config.ts`
- Modify: `packages/grid-agent/src/grid_agent/trajectory/api/app.py`
- Modify: `packages/grid-agent/tests/trajectory/api/test_app.py`
- Modify: `packages/grid-agent/pyproject.toml`
- Create/update: `packages/grid-agent/src/grid_agent/trajectory/static/*`
- Modify: `Makefile`, `.gitignore`, `docs/RUNBOOK.md`, and `docs/MANUAL-VALIDATION.md`.

**Interfaces:**
- Vite output directory is `packages/grid-agent/src/grid_agent/trajectory/static` with stable `assets/app.js`, `assets/app.css`, and `index.html`.
- API routes are registered before static routes; `/api/*` never falls back to the SPA.
- `GET /` and non-API client routes return `index.html`; missing static assets fail server startup with a typed diagnostic.
- Make targets: `setup-workbench`, `build-workbench`, `test-workbench`, and `trajectory`; `setup` includes workbench installation/build.

- [ ] **Step 1: Write failing backend static-route tests**

```python
def test_spa_is_served_with_self_only_csp(tmp_path: Path) -> None:
    app = create_test_app(static_root=write_static_fixture(tmp_path))
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "<script type=\"module\" src=\"/assets/app.js\"></script>" in response.text


def test_api_404_never_falls_back_to_spa(tmp_path: Path) -> None:
    response = TestClient(create_test_app(static_root=write_static_fixture(tmp_path))).get("/api/not-a-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_server_rejects_missing_production_assets(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="build-workbench"):
        create_test_app(static_root=tmp_path / "missing")
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q`

Expected: FAIL because the API app does not serve or validate SPA assets.

- [ ] **Step 3: Configure deterministic Vite output and safe static routes**

```ts
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../grid-agent/src/grid_agent/trajectory/static',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/chunk-[name]-[hash].js',
        assetFileNames: asset => asset.name?.endsWith('.css') ? 'assets/app.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
```

```python
def mount_workbench(app: FastAPI, static_root: Path) -> None:
    index = static_root / "index.html"
    app_js = static_root / "assets/app.js"
    app_css = static_root / "assets/app.css"
    if not all(path.is_file() for path in (index, app_js, app_css)):
        raise RuntimeError("trajectory workbench assets are missing; run make build-workbench")
    app.mount("/assets", StaticFiles(directory=static_root / "assets", check_dir=True), name="trajectory-assets")

    @app.get("/{client_path:path}", include_in_schema=False)
    def spa(client_path: str) -> FileResponse:
        if client_path == "api" or client_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse(index, media_type="text/html; charset=utf-8")
```

Register `mount_workbench` only after all API routes. Add Hatch force-include/package settings for `src/grid_agent/trajectory/static`. Make `trajectory` depend on `build-workbench`; keep Playwright reports, test-results, Vite cache, and coverage ignored while tracking production assets and screenshot baselines.

- [ ] **Step 4: Build and run static/API tests**

Run: `npm run build --prefix packages/trajectory-workbench && uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q && git diff --check`

Expected: deterministic assets exist, API/static tests pass, and no inline script/style violates CSP.

- [ ] **Step 5: Commit**

```bash
git add packages/trajectory-workbench packages/grid-agent/src/grid_agent/trajectory/api/app.py packages/grid-agent/tests/trajectory/api/test_app.py packages/grid-agent/pyproject.toml packages/grid-agent/src/grid_agent/trajectory/static Makefile .gitignore docs/RUNBOOK.md docs/MANUAL-VALIDATION.md
git commit -m "feat: serve trajectory workbench"
```

### Task 7: Performance and complete release gate

**Files:**
- Modify: frontend fixtures/E2E tests when required by measured performance only.
- Verify: all platform source and tests.

**Interfaces:**
- Performance acceptance: 100,000-event fixture initial API response ≤500 records/2 MiB; mounted trajectory rows ≤120; no request fetches the full event log; prepend retains visible semantic anchor.
- Produces verification evidence only unless a measured failure requires a tested fix.

- [ ] **Step 1: Run frontend type/unit/performance tests**

Run: `npm run check --prefix packages/trajectory-workbench && npm test --prefix packages/trajectory-workbench`

Expected: typecheck and all unit/component tests pass, including 100k DOM and anchor bounds.

- [ ] **Step 2: Run browser interaction, accessibility, and visual gates**

Run: `npm run test:e2e --prefix packages/trajectory-workbench`

Expected: run selection, cursor prepend, search, folding, timeline focus, context time travel, artifact drill-down, keyboard-only operation, axe, dark/light, wide/narrow, and all state screenshots pass.

- [ ] **Step 3: Run backend/API/golden gates serially**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q && make test-trajectory-golden`

Expected: all trajectory backend tests pass; golden run remains unchanged and reports 9 turns, 36 paired calls, and Q7 lineage.

- [ ] **Step 4: Run existing project release gates serially**

Run: `make doctor && make test && make test-e2e && make validate`

Expected: all existing non-provider gates pass with the stdout envelope, simulator boundary, current-run evidence, report, and continuous Analysis contracts intact.

- [ ] **Step 5: Perform local manual acceptance**

Run: `make trajectory PORT=8765`

Expected: open `http://127.0.0.1:8765`, select `analysis-20260814T081822Z`, confirm Business is default, Q7 drills through failed N-1 judgment → exact context revision → contingency result → evidence, then verify Agent/Context/Evidence tabs, theme, keyboard navigation, and responsive inspector. Stop with Ctrl-C; no run file changes.

- [ ] **Step 6: Inspect the release boundary**

Run: `git status --short && git log --oneline -8`

Expected: no uncommitted implementation or generated changes; six task commits are visible. Provider validation remains optional and is not run without explicit credentials.

## Self-Review

- Spec coverage: four-region shell, business-first view, full Agent ledger/timing/retries/tools, event-level Context time travel, Evidence relationships, inspector, timeline, search/fold, cursor prepend, stable identity, 100k virtualization, all async states, keyboard/ARIA, themes, responsive behavior, CSP-safe production serving, screenshot regression, and full integration gates are covered.
- Visual authority is durable: `docs/superpowers/mockups/2026-08-14-trajectory-workbench.html` is versioned and every screenshot baseline is reviewed against it.
- Deferred intentionally: live streaming, cross-run analytics, annotations/editing, graph visualization, and remote hosting remain out of scope.
- Type consistency: TypeScript API models mirror the read-only API plan and no UI code reads run files directly.
