import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type TrajectoryApiClient } from '../api/client';
import type { AgentEventRow, AgentPageRequest, AgentTurn, BusinessCausalRow, BusinessNode, BusinessProblem, ContextFrame, ContextFrameSummary, EvidenceIndex, EvidencePageRequest, EvidenceRecord, ExecutionSlice, ProjectionPage, RunListResponse } from '../api/types';
import { App } from './App';

const run: RunListResponse = {
  items: [{
    analysis_id: 'analysis-test', status: 'completed', source_kind: 'native',
    started_at: '2026-08-14T08:18:22Z', turn_count: 9, last_sequence: 78,
    replay_trusted_through: 78, diagnostic: null,
  }, {
    analysis_id: 'analysis-partial', status: 'partial', source_kind: 'imported',
    started_at: '2026-08-14T08:18:22Z', turn_count: 4, last_sequence: 43,
    replay_trusted_through: 43, diagnostic: 'missing tail',
  }, {
    analysis_id: 'analysis-corrupt', status: 'corrupt', source_kind: 'native',
    started_at: '2026-08-14T08:18:22Z', turn_count: 0, last_sequence: 0,
    replay_trusted_through: 0, diagnostic: 'invalid event',
  }],
};

const problems: BusinessProblem[] = [
  {
    id: 'business:7', source: 'derived', source_sequences: [59, 78], rule_id: 'business/v1',
    status: 'completed', unavailable_reason: null, source_sequence: 59, turn_id: 'analysis-test-t007',
    title: 'Q7 · 线路 17 N-1', node_count: 2, nodes: [{
      id: 'business:7:opened', source: 'observed', source_sequences: [59], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: 59, kind: 'decision',
      title: 'Problem opened', detail: null, refs: [],
    }, {
      id: 'business:7:closed', source: 'observed', source_sequences: [78], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: 78, kind: 'decision',
      title: 'Problem completed', detail: null, refs: [],
    }],
  },
];

const nestedProblem: BusinessProblem = {
  ...problems[0],
  nodes: [{
    id: 'business:7:claim', source: 'agent-declared', source_sequences: [61], rule_id: null,
    status: 'completed', unavailable_reason: null, source_sequence: 61, kind: 'claim',
    title: 'Nested conclusion', detail: null, refs: [],
  }],
};

function fixtureClient(): Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> {
  return {
    listRuns: async () => run,
    getBusinessPage: async (analysisId) => businessProjectionPage(problems, { analysisId }),
  };
}

function businessProjectionPage(
  groupedProblems: BusinessProblem[],
  options: {
    analysisId?: string;
    olderCursor?: string | null;
    hasOlder?: boolean;
    firstSequence?: number | null;
    lastSequence?: number | null;
  } = {},
): ProjectionPage<BusinessCausalRow> {
  const items = groupedProblems.flatMap((problem) => problem.nodes.map((node) => ({
    id: `${problem.id}:sequence:${node.source_sequence}`,
    source_sequence: node.source_sequence,
    problem: {
      id: problem.id,
      source: problem.source,
      rule_id: problem.rule_id,
      status: problem.status,
      unavailable_reason: problem.unavailable_reason,
      turn_id: problem.turn_id,
      title: problem.title,
      first_sequence: Math.min(...problem.source_sequences),
      last_sequence: Math.max(...problem.source_sequences),
      node_count: Math.max(problem.node_count ?? 0, problem.nodes.length),
    },
    nodes: [businessWireNode(node)],
  })));
  return {
    analysis_id: options.analysisId ?? 'analysis-test',
    items,
    older_cursor: options.olderCursor ?? null,
    newer_cursor: null,
    first_sequence: options.firstSequence ?? items[0]?.source_sequence ?? null,
    last_sequence: options.lastSequence ?? items.at(-1)?.source_sequence ?? null,
    has_older: options.hasOlder ?? false,
    encoded_bytes: 100,
  };
}

function businessWireNode(node: BusinessNode): Omit<BusinessNode, 'source_sequence'> {
  const { source_sequence, ...wireNode } = node;
  void source_sequence;
  return wireNode;
}

function evidenceRecord(reference: string, sequence: number): EvidenceRecord {
  return {
    id: `artifact:${reference}`, source: 'observed', source_sequences: [sequence], rule_id: null,
    status: 'completed', unavailable_reason: null, reference, kind: 'evidence',
    relative_path: `evidence/${reference}.json`, sha256: 'a'.repeat(64), verification_status: 'verified',
    producing_sequence: sequence, consuming_sequences: [], turn_id: null, step_id: null,
    request_id: null, tool_call_id: null, result_id: null, evidence_id: reference, claim_id: null,
  };
}

function agentEventRow(
  id: string,
  sequence: number,
  overrides: Partial<AgentEventRow> = {},
): AgentEventRow {
  return {
    id,
    parent_id: null,
    turn_id: 'analysis-test-t007',
    kind: 'tool',
    level: 4,
    source_sequence: sequence,
    source: 'observed',
    status: 'completed',
    title: `Tool ${sequence}`,
    detail: null,
    ...overrides,
  };
}

function agentProjectionPage(
  items: AgentEventRow[],
  olderCursor: string | null = null,
  hasOlder = false,
): ProjectionPage<AgentEventRow> {
  return {
    analysis_id: 'analysis-test',
    items,
    older_cursor: olderCursor,
    newer_cursor: null,
    first_sequence: items[0]?.source_sequence ?? null,
    last_sequence: items.at(-1)?.source_sequence ?? null,
    has_older: hasOlder,
    encoded_bytes: 100,
  };
}

function viewTab(name: 'Business' | 'Agent' | 'Context' | 'Evidence') {
  return within(screen.getByRole('tablist', { name: 'Trajectory views' })).getByRole('tab', { name });
}

describe('App shell', () => {
  afterEach(() => {
    cleanup();
    window.history.replaceState({}, '', '/');
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
    vi.unstubAllGlobals();
  });

  it('uses the system theme until an explicit toggle persists a light or dark preference', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-color-scheme: dark)' ? false : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));

    render(<App client={fixtureClient()} />);

    await screen.findByRole('navigation', { name: 'Runs' });
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');

    fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }));

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    expect(window.localStorage.getItem('trajectory-workbench.theme')).toBe('dark');
  });
  it('renders the approved four-region hierarchy and business tab as selected', async () => {
    render(<App client={fixtureClient()} />);

    expect(await screen.findByRole('navigation', { name: 'Runs' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Run overview timeline' })).toBeVisible();
    expect(viewTab('Business')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
  });

  it('shows a loading state while the run list is being requested', () => {
    render(<App client={{ listRuns: () => new Promise<RunListResponse>(() => undefined), getBusinessPage: vi.fn() }} />);

    expect(screen.getByTestId('state-loading')).toHaveTextContent('Loading runs');
  });

  it('shows an empty state when the run list has no items', async () => {
    render(<App client={{ listRuns: async () => ({ items: [] }), getBusinessPage: vi.fn() }} />);

    expect(await screen.findByTestId('state-empty')).toHaveTextContent('No runs available');
  });

  it('retries a failed run-list request', async () => {
    const listRuns = vi.fn()
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce(run);
    render(<App client={{ ...fixtureClient(), listRuns }} />);

    const error = await screen.findByTestId('state-network-error');
    expect(error).toHaveAttribute('role', 'alert');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('navigation', { name: 'Runs' })).toBeVisible();
    expect(listRuns).toHaveBeenCalledTimes(2);
  });

  it('shows a partial-run status without hiding its durable projection', async () => {
    render(<App client={fixtureClient()} />);

    fireEvent.click(await screen.findByRole('button', { name: /analysis-partial/i }));

    expect(await screen.findByTestId('state-partial')).toBeVisible();
    expect(await screen.findByText('Q7 · 线路 17 N-1')).toBeVisible();
  });

  it('blocks the projection for a corrupt run', async () => {
    render(<App client={fixtureClient()} />);

    fireEvent.click(await screen.findByRole('button', { name: /analysis-corrupt/i }));

    expect(await screen.findByTestId('state-corrupt')).toBeVisible();
    expect(screen.queryByText('Q7 · 线路 17 N-1')).not.toBeInTheDocument();
  });

  it('shows an unsupported state when the runs API returns 501', async () => {
    render(<App client={{ listRuns: async () => { throw new ApiError(501, 'unsupported', 'Upgrade the workbench.'); }, getBusinessPage: vi.fn() }} />);

    expect(await screen.findByTestId('state-unsupported')).toHaveTextContent('Upgrade the workbench.');
  });

  it('retries a failed business projection request', async () => {
    const getBusinessPage = vi.fn()
      .mockRejectedValueOnce(new Error('projection unavailable'))
      .mockResolvedValueOnce(businessProjectionPage(problems));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    expect(await screen.findByTestId('state-network-error')).toHaveTextContent('projection unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Q7 · 线路 17 N-1')).toBeVisible();
    expect(getBusinessPage).toHaveBeenCalledTimes(2);
  });

  it('shows unsupported when a business projection returns HTTP 501', async () => {
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => { throw new ApiError(501, 'unsupported', 'Business projection requires a newer workbench.'); },
    }} />);

    expect(await screen.findByTestId('state-unsupported')).toHaveTextContent('Business projection requires a newer workbench.');
  });

  it('selecting Q7 synchronizes timeline, content, and inspector', async () => {
    render(<App client={fixtureClient()} />);

    fireEvent.click(await screen.findByRole('button', { name: /Q7.*overview segment/i }));

    expect(screen.getByRole('region', { name: 'Run overview timeline' }))
      .toHaveAttribute('data-focused-turn', 'analysis-test-t007');
    expect(screen.getByRole('main')).toHaveTextContent('Q7 · 线路 17 N-1');
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' }))
      .toHaveTextContent('analysis-test-t007');
  });

  it('selecting a problem in the rail focuses its causal group without replacing node selection', async () => {
    const selectedProblem: BusinessProblem = {
      ...problems[0],
      title: 'Q7 · Line 17 N-1',
      nodes: [
        {
          id: 'business:7:claim', source: 'agent-declared', source_sequences: [61], rule_id: null,
          status: 'completed', unavailable_reason: null, source_sequence: 61, kind: 'claim',
          title: 'Nested conclusion', detail: null, refs: [],
        },
        {
          id: 'business:7:evidence', source: 'observed', source_sequences: [62], rule_id: null,
          status: 'completed', unavailable_reason: null, source_sequence: 62, kind: 'evidence',
          title: 'Evidence collected', detail: null, refs: [],
        },
        {
          id: 'business:7:decision', source: 'derived', source_sequences: [63], rule_id: null,
          status: 'completed', unavailable_reason: null, source_sequence: 63, kind: 'decision',
          title: 'Decision recorded', detail: null, refs: [],
        },
      ],
    };
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([selectedProblem]),
    }} />);

    fireEvent.click(await screen.findByRole('button', { name: /Nested conclusion/i }));
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('business:7:claim');

    fireEvent.click(screen.getByRole('button', { name: /Q7.*3 decisions/i }));

    expect(screen.getByRole('heading', { name: /Q7.*Line 17/i })).toBeVisible();
    expect(screen.getByRole('heading', { name: /Q7.*Line 17/i })).toHaveFocus();
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('business:7:claim');
  });

  it('keyboard tabs move without a pointer', async () => {
    render(<App client={fixtureClient()} />);
    await screen.findByRole('navigation', { name: 'Runs' });
    const business = viewTab('Business');

    business.focus();
    fireEvent.keyDown(business, { key: 'ArrowRight' });

    expect(viewTab('Agent')).toHaveFocus();
  });

  it('renders flat Agent rows, applies filters, and retries the exact failed older cursor', async () => {
    let olderAttempts = 0;
    const current = agentEventRow('tool:current', 74, { title: 'Current gridctl tool' });
    const older = agentEventRow('tool:older', 44, { title: 'Older gridctl tool' });
    const getAgentPage = vi.fn(async (_runId: string, request: AgentPageRequest = { filters: {} }): Promise<ProjectionPage<AgentEventRow>> => {
      if (request.cursor) {
        olderAttempts += 1;
        if (olderAttempts === 1) throw new Error('older agent cursor unavailable');
        return agentProjectionPage([older]);
      }
      return agentProjectionPage([current], 'opaque/agent-cursor', true);
    });
    render(<App client={{ ...fixtureClient(), getAgentPage }} />);

    fireEvent.click(viewTab('Agent'));
    expect(await screen.findByText('Current gridctl tool')).toBeVisible();
    fireEvent.change(screen.getByLabelText('Agent capability'), { target: { value: 'gridctl' } });
    await waitFor(() => expect(getAgentPage).toHaveBeenCalledWith('analysis-test', {
      filters: { capability: 'gridctl' },
    }, expect.any(AbortSignal)));

    fireEvent.click(screen.getByRole('button', { name: 'Load older agent history' }));
    expect(await screen.findByText('older agent cursor unavailable')).toBeVisible();
    expect(screen.getByText('Current gridctl tool')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Retry older agent history' }));

    expect(await screen.findByText('Older gridctl tool')).toBeVisible();
    expect(getAgentPage).toHaveBeenNthCalledWith(4, 'analysis-test', {
      cursor: 'opaque/agent-cursor',
      filters: { capability: 'gridctl' },
    }, expect.any(AbortSignal));
  });

  it('pages Context summaries and fetches exact detail only after selecting a frame', async () => {
    const summaries: ContextFrameSummary[] = [{
      id: 'context:42', source_sequence: 42, before_revision: 8, after_revision: 9,
      changed: true, request_input_available: true, event_kind: 'tool-result',
    }];
    const getContextPage = vi.fn(async (): Promise<ProjectionPage<ContextFrameSummary>> => ({
      analysis_id: 'analysis-test', items: summaries, older_cursor: null, newer_cursor: null,
      first_sequence: 42, last_sequence: 42, has_older: false, encoded_bytes: 80,
    }));
    const getContextFrame = vi.fn(async (_runId: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: 8, after_revision: 9, before_state_hash: 'before', after_state_hash: 'after',
      before_state: { revision: 8 }, delta: { revision: 9 }, after_state: { revision: 9 },
      max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    render(<App client={{ ...fixtureClient(), getContextPage, getContextFrame }} />);

    fireEvent.click(viewTab('Context'));
    expect(await screen.findByRole('button', { name: /sequence 42.*tool-result/i })).toBeVisible();
    expect(getContextFrame).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /sequence 42.*tool-result/i }));
    await waitFor(() => expect(getContextFrame).toHaveBeenCalledWith('analysis-test', 42, expect.any(AbortSignal)));
    expect(await screen.findByText(/Authoritative state at sequence 42/i)).toBeVisible();
  });

  it('ignores an exact Context detail that resolves after its summary filters change', async () => {
    const summary: ContextFrameSummary = {
      id: 'context:42', source_sequence: 42, before_revision: 8, after_revision: 9,
      changed: true, request_input_available: true, event_kind: 'tool-result',
    };
    const getContextPage = vi.fn(async (): Promise<ProjectionPage<ContextFrameSummary>> => ({
      analysis_id: 'analysis-test', items: [summary], older_cursor: null, newer_cursor: null,
      first_sequence: 42, last_sequence: 42, has_older: false, encoded_bytes: 80,
    }));
    const pendingDetails: Array<{ signal: AbortSignal; resolve: (frame: ContextFrame) => void }> = [];
    const getContextFrame = vi.fn((_runId: string, _sequence: number, signal?: AbortSignal) => new Promise<ContextFrame>((resolve) => {
      pendingDetails.push({ signal: signal ?? new AbortController().signal, resolve });
    }));
    render(<App client={{ ...fixtureClient(), getContextPage, getContextFrame }} />);

    fireEvent.click(viewTab('Context'));
    fireEvent.click(await screen.findByRole('button', { name: /sequence 42.*tool-result/i }));
    await waitFor(() => expect(getContextFrame).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText('Context changed state'), { target: { value: 'true' } });
    await waitFor(() => expect(getContextPage).toHaveBeenLastCalledWith('analysis-test', {
      filters: { changed: true },
    }, expect.any(AbortSignal)));
    await waitFor(() => expect(getContextFrame).toHaveBeenCalledTimes(2));
    expect(pendingDetails[0].signal.aborted).toBe(true);

    await act(async () => pendingDetails[0].resolve({
      id: 'context:42:old-filter', source: 'observed', source_sequences: [42], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: 42,
      before_revision: 8, after_revision: 9, before_state_hash: 'before', after_state_hash: 'after',
      before_state: { filter: 'old' }, delta: {}, after_state: { filter: 'old' },
      max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));

    expect(screen.queryByRole('heading', { name: 'Authoritative state at sequence 42' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pin sequence 42 as frame A' })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Pinned frame comparison' })).toHaveTextContent('Pin frame A · Pin frame B');
  });

  it('retains Context summaries and retries the identical failed opaque cursor', async () => {
    let olderAttempts = 0;
    const summary = (sequence: number): ContextFrameSummary => ({
      id: `context:${sequence}`, source_sequence: sequence, before_revision: sequence - 1,
      after_revision: sequence, changed: true, request_input_available: true, event_kind: 'context-frame',
    });
    const getContextPage = vi.fn(async (_runId: string, request?: { cursor?: string; filters: object }): Promise<ProjectionPage<ContextFrameSummary>> => {
      if (request?.cursor) {
        olderAttempts += 1;
        if (olderAttempts === 1) throw new Error('older context cursor unavailable');
        return { analysis_id: 'analysis-test', items: [summary(41)], older_cursor: null, newer_cursor: null, first_sequence: 41, last_sequence: 41, has_older: false, encoded_bytes: 80 };
      }
      return { analysis_id: 'analysis-test', items: [summary(42)], older_cursor: 'opaque/context-cursor', newer_cursor: null, first_sequence: 42, last_sequence: 42, has_older: true, encoded_bytes: 80 };
    });
    render(<App client={{ ...fixtureClient(), getContextPage }} />);

    fireEvent.click(viewTab('Context'));
    expect(await screen.findByRole('button', { name: /sequence 42/i })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Load older context history' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('older context cursor unavailable');
    expect(screen.getByRole('button', { name: /sequence 42/i })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Retry older context history' }));

    expect(await screen.findByRole('button', { name: /sequence 41/i })).toBeVisible();
    expect(getContextPage).toHaveBeenLastCalledWith('analysis-test', {
      cursor: 'opaque/context-cursor', filters: {},
    }, expect.any(AbortSignal));
  });

  it('activates the Q7 overview segment with Enter and Space', async () => {
    render(<App client={fixtureClient()} />);
    const segment = await screen.findByRole('button', { name: /Q7.*overview segment/i });

    segment.focus();
    fireEvent.keyDown(segment, { key: 'Enter' });
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('analysis-test-t007');

    fireEvent.keyDown(segment, { key: ' ' });
    expect(screen.getByRole('region', { name: 'Run overview timeline' }))
      .toHaveAttribute('data-focused-turn', 'analysis-test-t007');
  });

  it('keeps timeline controls outside its SVG visual', async () => {
    render(<App client={fixtureClient()} />);

    const segment = await screen.findByRole('button', { name: /Q7.*overview segment/i });
    const region = screen.getByRole('region', { name: 'Run overview timeline' });
    const visual = region.querySelector('svg');
    if (!visual) throw new Error('timeline visual is missing');

    expect(segment.tagName).toBe('BUTTON');
    expect(visual).toHaveAttribute('aria-hidden', 'true');
    expect(visual).toHaveAttribute('focusable', 'false');
    expect(visual).not.toHaveAttribute('role');
    expect(visual).not.toHaveAttribute('aria-label');
    expect(visual.querySelector('[role="button"], button, [tabindex]:not([tabindex="-1"])')).toBeNull();
  });

  it('persists a selected trajectory item in the same-origin deep link', async () => {
    window.history.replaceState({}, '', '/');
    render(<App client={fixtureClient()} />);

    fireEvent.click(await screen.findByRole('button', { name: /Q7.*overview segment/i }));

    expect(new URLSearchParams(window.location.search).get('node')).toBe('analysis-test-t007');
  });

  it('resolves a nested business node deep link to its exact inspector node while retaining the parent timeline turn', async () => {
    window.history.replaceState({}, '', '/?node=business:7:claim');
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([nestedProblem]),
    }} />);

    await screen.findByRole('button', { name: /nested conclusion/i });
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('business:7:claim');
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('Nested conclusion');
    expect(screen.getByRole('region', { name: 'Run overview timeline' })).toHaveAttribute('data-focused-turn', 'analysis-test-t007');
  });

  it('uses a selected business node’s own sequence and artifact references in context and evidence', async () => {
    const node = { ...nestedProblem.nodes[0], source_sequence: 61, refs: ['evidence:nested'] };
    const getContextFrame = vi.fn(async (_id: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    const getEvidenceIndex = vi.fn(async (): Promise<EvidenceIndex> => ({ analysis_id: 'analysis-test', records: {
      'evidence:nested': { id: 'artifact:nested', source: 'observed', source_sequences: [61], rule_id: null, status: 'completed', unavailable_reason: null, reference: 'evidence:nested', kind: 'evidence', relative_path: 'evidence/nested.json', sha256: 'a'.repeat(64), verification_status: 'verified', producing_sequence: 61, consuming_sequences: [], turn_id: null, step_id: null, request_id: null, tool_call_id: null, result_id: null, evidence_id: null, claim_id: null },
    } }));
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([{ ...nestedProblem, nodes: [node] }]),
      getContextFrame,
      getEvidenceIndex,
      artifactUrl: (_runId, ref) => `/artifact/${ref}`,
    }} />);

    fireEvent.click(await screen.findByRole('button', { name: /nested conclusion/i }));
    fireEvent.click(viewTab('Context'));
    await waitFor(() => expect(getContextFrame).toHaveBeenLastCalledWith('analysis-test', 61, expect.any(AbortSignal)));

    fireEvent.click(viewTab('Evidence'));
    expect(await screen.findByRole('row', { selected: true })).toHaveTextContent('evidence:nested');

    fireEvent.click(viewTab('Business'));
    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    fireEvent.click(within(inspector).getByRole('tab', { name: 'Evidence' }));
    expect(await within(inspector).findByRole('link', { name: 'evidence:nested' })).toHaveAttribute('href', '/artifact/evidence:nested');
  });

  it('fetches selected audit evidence by exact reference when it is outside the current page', async () => {
    const reference = 'evidence:outside-first-page';
    const node = { ...nestedProblem.nodes[0], refs: [reference] };
    const page = (items: EvidenceRecord[]): ProjectionPage<EvidenceRecord> => ({
      analysis_id: 'analysis-test', items, older_cursor: null, newer_cursor: null,
      first_sequence: items[0]?.producing_sequence ?? null,
      last_sequence: items.at(-1)?.producing_sequence ?? null,
      has_older: false, encoded_bytes: 100,
    });
    const getEvidencePage = vi.fn(async (_runId: string, request?: EvidencePageRequest) => (
      request?.filters.relevant_ref === reference
        ? page([evidenceRecord(reference, 61)])
        : page([evidenceRecord('evidence:first-page-only', 78)])
    ));
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([{ ...nestedProblem, nodes: [node] }]),
      getEvidencePage,
      artifactUrl: (_runId, ref) => `/artifact/${ref}`,
    }} />);

    fireEvent.click(await screen.findByRole('button', { name: /nested conclusion/i }));
    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    fireEvent.click(within(inspector).getByRole('tab', { name: 'Evidence' }));

    expect(await within(inspector).findByRole('link', { name: reference })).toHaveAttribute('href', `/artifact/${reference}`);
    expect(getEvidencePage).toHaveBeenCalledWith('analysis-test', {
      filters: { relevant_ref: reference },
    }, expect.any(AbortSignal));
  });

  it('shows selected claim evidence with verified digest and jumps to the producing sequence', async () => {
    const auditedProblem: BusinessProblem = {
      ...problems[0],
      nodes: [
        {
          id: 'tool:17',
          source: 'observed',
          source_sequences: [47],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 47,
          kind: 'tool',
          title: 'Power flow tool result',
          detail: null,
          refs: ['evidence:line-17'],
        },
        {
          id: 'claim:7',
          source: 'agent-declared',
          source_sequences: [61],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 61,
          kind: 'claim',
          title: 'Line 17 overload conclusion',
          detail: 'Line 17 overloads after the contingency.',
          refs: ['evidence:line-17'],
        },
      ],
    };
    const agentTurn: AgentTurn = {
      id: 'agent-turn:7',
      source: 'observed',
      source_sequences: [45, 61],
      rule_id: null,
      status: 'completed',
      unavailable_reason: null,
      source_sequence: 45,
      turn_id: auditedProblem.turn_id,
      ordinal: 7,
      steps: [],
    };
    const getAgentPage = vi.fn(async () => ({
      analysis_id: 'analysis-test',
      items: [agentTurn],
      older_cursor: null,
      newer_cursor: null,
      first_sequence: 45,
      last_sequence: 61,
      has_older: false,
      encoded_bytes: 100,
    }));
    const getEvidenceIndex = vi.fn(async (): Promise<EvidenceIndex> => ({ analysis_id: 'analysis-test', records: {
      'evidence:line-17': {
        id: 'record:line-17',
        source: 'observed',
        source_sequences: [47],
        rule_id: null,
        status: 'completed',
        unavailable_reason: null,
        reference: 'evidence:line-17',
        kind: 'tool-result',
        relative_path: 'artifacts/line-17.json',
        sha256: 'a'.repeat(64),
        verification_status: 'verified',
        producing_sequence: 47,
        consuming_sequences: [61],
        turn_id: auditedProblem.turn_id,
        step_id: 'step-2',
        request_id: 'request-2',
        tool_call_id: 'tool-17',
        result_id: 'result-17',
        evidence_id: null,
        claim_id: 'claim:7',
      },
    } }));
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([auditedProblem], { firstSequence: 47, lastSequence: 61 }),
      getAgentPage,
      getEvidenceIndex,
      artifactUrl: (_runId, ref) => `/artifact/${ref}`,
    }} />);

    fireEvent.click(await screen.findByTestId('causal-node-claim:7'));
    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    fireEvent.click(within(inspector).getByRole('tab', { name: 'Evidence' }));

    expect(await within(inspector).findByText(/verified/i)).toBeVisible();
    expect(within(inspector).getByText(/aaaaaaaaaaaa/i)).toBeVisible();

    fireEvent.click(within(inspector).getByRole('button', { name: /go to sequence 47/i }));

    expect(screen.getByTestId('causal-node-tool:17')).toHaveAttribute('aria-current', 'true');
  });

  it('aborts stale execution slice requests and displays only the new selected sequence', async () => {
    const auditedProblem: BusinessProblem = {
      ...problems[0],
      nodes: [
        {
          id: 'tool:17',
          source: 'observed',
          source_sequences: [48],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 48,
          kind: 'tool',
          title: 'Power flow tool result',
          detail: null,
          refs: [],
        },
        {
          id: 'claim:7',
          source: 'agent-declared',
          source_sequences: [61],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 61,
          kind: 'claim',
          title: 'Line 17 overload conclusion',
          detail: null,
          refs: [],
        },
      ],
    };
    const pending: {
      sequence: number;
      signal: AbortSignal;
      resolve: (slice: ExecutionSlice) => void;
    }[] = [];
    const getExecutionSlice = vi.fn((_id: string, sequence: number, signal?: AbortSignal) => new Promise<ExecutionSlice>((resolve) => {
      pending.push({ sequence, signal: signal ?? new AbortController().signal, resolve });
    }));
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([auditedProblem], { firstSequence: 48, lastSequence: 61 }),
      getExecutionSlice,
    }} />);

    fireEvent.click(await screen.findByTestId('causal-node-tool:17'));
    await waitFor(() => expect(getExecutionSlice).toHaveBeenLastCalledWith('analysis-test', 48, expect.any(AbortSignal)));
    fireEvent.click(screen.getByTestId('causal-node-claim:7'));
    await waitFor(() => expect(getExecutionSlice).toHaveBeenLastCalledWith('analysis-test', 61, expect.any(AbortSignal)));

    expect(pending[0].signal.aborted).toBe(true);

    await act(async () => {
      pending[0].resolve({
        analysis_id: 'analysis-test',
        source_sequence: 48,
        lineage: {
          business_node_ids: ['tool:17'], artifact_refs: [],
          agent_node_ids: ['agent-turn:stale'], turn_ids: ['stale-turn-48'],
          step_ids: [], request_ids: [], tool_call_ids: [], result_ids: [],
        },
        turn: {
          id: 'agent-turn:stale',
          source: 'observed',
          source_sequences: [48],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 48,
          turn_id: 'stale-turn-48',
          ordinal: 6,
          steps: [],
        },
        unavailable_reason: null,
      });
      pending[1].resolve({
        analysis_id: 'analysis-test',
        source_sequence: 61,
        lineage: {
          business_node_ids: ['claim:7'], artifact_refs: [],
          agent_node_ids: ['agent-turn:fresh'], turn_ids: ['fresh-turn-61'],
          step_ids: [], request_ids: [], tool_call_ids: [], result_ids: [],
        },
        turn: {
          id: 'agent-turn:fresh',
          source: 'observed',
          source_sequences: [61],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          source_sequence: 61,
          turn_id: 'fresh-turn-61',
          ordinal: 7,
          steps: [],
        },
        unavailable_reason: null,
      });
    });

    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    fireEvent.click(within(inspector).getByRole('tab', { name: 'Execution' }));

    expect(await within(inspector).findByText('fresh-turn-61')).toBeVisible();
    expect(within(inspector).queryByText('stale-turn-48')).not.toBeInTheDocument();
  });

  it('rehydrates a persisted context deep link and fetches its exact sequence', async () => {
    const getContextFrame = vi.fn(async (_id: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    window.history.replaceState({}, '', '/?node=context:42');
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    await waitFor(() => expect(getContextFrame).toHaveBeenCalledWith('analysis-test', 42, expect.any(AbortSignal)));
    expect(viewTab('Context')).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText(/state at sequence 42/i)).toBeVisible();
  });

  it('ignores a malformed persisted context deep link without requesting a frame', async () => {
    const getContextFrame = vi.fn();
    window.history.replaceState({}, '', '/?node=context:not-a-sequence');
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    await screen.findByRole('navigation', { name: 'Runs' });
    expect(getContextFrame).not.toHaveBeenCalled();
    expect(viewTab('Business')).toHaveAttribute('aria-selected', 'true');
  });

  it('fetches the older cursor once and prepends its problems before the current page', async () => {
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce(businessProjectionPage([problems[0]], { olderCursor: 'older-page', hasOlder: true }))
      .mockResolvedValueOnce(businessProjectionPage([{ ...problems[0], id: 'business:6', title: 'Q6 · Earlier' }], { firstSequence: 1, lastSequence: 58 }));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    await screen.findByRole('button', { name: /fold q7/i });
    fireEvent.click(screen.getByRole('button', { name: 'Load older history' }));

    await waitFor(() => expect(getBusinessPage).toHaveBeenLastCalledWith('analysis-test', 'older-page', expect.any(AbortSignal)));
    expect(await screen.findByText('Q6 · Earlier')).toBeVisible();
    expect(screen.getByText('Q6 · Earlier').compareDocumentPosition(screen.getByText('Q7 · 线路 17 N-1')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows unsupported when loading an older business cursor returns HTTP 501', async () => {
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce(businessProjectionPage([problems[0]], { olderCursor: 'older-page', hasOlder: true }))
      .mockRejectedValueOnce(new ApiError(501, 'unsupported', 'Older business history requires a newer workbench.'));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Load older history' }));

    expect(await screen.findByTestId('state-unsupported')).toHaveTextContent('Older business history requires a newer workbench.');
    expect(getBusinessPage).toHaveBeenLastCalledWith('analysis-test', 'older-page', expect.any(AbortSignal));
  });

  it('retries a failed older business cursor instead of the initial page', async () => {
    const olderProblem = { ...problems[0], id: 'business:6', title: 'Q6 · Earlier' };
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce(businessProjectionPage([problems[0]], { olderCursor: 'cursor-before-48', hasOlder: true }))
      .mockRejectedValueOnce(new Error('older history unavailable'))
      .mockResolvedValueOnce(businessProjectionPage([olderProblem], { firstSequence: 1, lastSequence: 58 }));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Load older history' }));
    expect(await screen.findByText('older history unavailable')).toBeVisible();
    expect(screen.getByText('Q7 · 线路 17 N-1')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Retry older history' }));

    expect(await screen.findByText('Q6 · Earlier')).toBeVisible();
    expect(getBusinessPage).toHaveBeenNthCalledWith(3, 'analysis-test', 'cursor-before-48', expect.any(AbortSignal));
  });

  it('filters by source kind and groups visible runs by status', async () => {
    render(<App client={fixtureClient()} />);
    await screen.findByRole('navigation', { name: 'Runs' });

    expect(screen.getByRole('heading', { name: 'Completed runs' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Partial runs' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Corrupt runs' })).toBeVisible();

    fireEvent.change(screen.getByLabelText('Source kind'), { target: { value: 'imported' } });

    expect(screen.getByRole('button', { name: /analysis-partial/i })).toBeVisible();
    expect(screen.queryByRole('button', { name: /analysis-test/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Completed runs' })).not.toBeInTheDocument();
  });

  it('keeps inspector controls in the keyboard focus order', async () => {
    render(<App client={fixtureClient()} />);
    await screen.findByRole('navigation', { name: 'Runs' });
    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    const inspectorTab = within(inspector).getByRole('tab', { name: 'Overview' });

    inspectorTab.focus();
    expect(inspectorTab).toHaveFocus();
  });

  it('fetches the exact context frame selected by the sequence scrubber', async () => {
    const getContextFrame = vi.fn(async (_id: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    await screen.findByRole('navigation', { name: 'Runs' });
    fireEvent.click(viewTab('Context'));
    await screen.findByText(/state at sequence 78/i);
    fireEvent.change(screen.getByLabelText('Event sequence'), { target: { value: '42' } });

    await waitFor(() => expect(getContextFrame).toHaveBeenLastCalledWith('analysis-test', 42, expect.any(AbortSignal)));
    expect(await screen.findByText(/state at sequence 42/i)).toBeVisible();
  });

  it('keeps a scrubbed context sequence after selecting a business problem', async () => {
    const getContextFrame = vi.fn(async (_id: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    fireEvent.click(await screen.findByRole('button', { name: /Q7.*overview segment/i }));
    fireEvent.click(viewTab('Context'));
    await screen.findByText(/state at sequence 59/i);
    fireEvent.change(screen.getByLabelText('Event sequence'), { target: { value: '42' } });

    await waitFor(() => expect(getContextFrame).toHaveBeenLastCalledWith('analysis-test', 42, expect.any(AbortSignal)));
    expect(getContextFrame.mock.calls.map(([, sequence]) => sequence)).not.toContain(78);
    expect(await screen.findByText(/state at sequence 42/i)).toBeVisible();
  });

  it('recomputes and fetches context for a newly selected trajectory node', async () => {
    const getContextFrame = vi.fn(async (_id: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    }));
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    await screen.findByRole('navigation', { name: 'Runs' });
    fireEvent.click(viewTab('Context'));
    await screen.findByText(/state at sequence 78/i);
    fireEvent.click(screen.getByRole('button', { name: /Q7.*overview segment/i }));

    await waitFor(() => expect(getContextFrame).toHaveBeenLastCalledWith('analysis-test', 59, expect.any(AbortSignal)));
    expect(await screen.findByText(/state at sequence 59/i)).toBeVisible();
  });

  it('ignores an out-of-order business page after switching runs', async () => {
    const pending: Array<{
      runId: string;
      signal: AbortSignal;
      resolve: (page: ProjectionPage<BusinessCausalRow>) => void;
    }> = [];
    const getBusinessPage = vi.fn((runId: string, _cursor?: string, signal?: AbortSignal) => new Promise<ProjectionPage<BusinessCausalRow>>((resolve) => {
      pending.push({ runId, signal: signal ?? new AbortController().signal, resolve });
    }));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    fireEvent.click(await screen.findByRole('button', { name: /analysis-partial/i }));
    await waitFor(() => expect(pending.map(({ runId }) => runId)).toEqual(['analysis-test', 'analysis-partial']));
    expect(pending[0].signal.aborted).toBe(true);

    const page = (title: string): BusinessProblem => ({
      ...nestedProblem,
      id: `business:${title}`,
      turn_id: `${title}-turn`,
      title,
      nodes: [{ ...nestedProblem.nodes[0], id: `node:${title}`, title: `${title} node` }],
    });
    await act(async () => {
      pending[1].resolve(businessProjectionPage([page('fresh partial run')], { analysisId: 'analysis-partial' }));
      pending[0].resolve(businessProjectionPage([page('stale completed run')]));
    });

    expect((await screen.findAllByText('fresh partial run')).length).toBeGreaterThan(0);
    expect(screen.queryByText('stale completed run')).not.toBeInTheDocument();
  });

  it('ignores an out-of-order context frame after switching selected sequences', async () => {
    const twoNodes: BusinessProblem = {
      ...nestedProblem,
      nodes: [
        { ...nestedProblem.nodes[0], id: 'node:48', source_sequences: [48], source_sequence: 48, title: 'Sequence 48' },
        { ...nestedProblem.nodes[0], id: 'node:61', source_sequences: [61], source_sequence: 61, title: 'Sequence 61' },
      ],
    };
    const pending: Array<{ sequence: number; signal: AbortSignal; resolve: (frame: ContextFrame) => void }> = [];
    const getContextFrame = vi.fn((_runId: string, sequence: number, signal?: AbortSignal) => new Promise<ContextFrame>((resolve) => {
      pending.push({ sequence, signal: signal ?? new AbortController().signal, resolve });
    }));
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => businessProjectionPage([twoNodes], { firstSequence: 48, lastSequence: 61 }),
      getContextFrame,
    }} />);

    fireEvent.click(await screen.findByTestId('causal-node-node:48'));
    await waitFor(() => expect(pending.at(-1)?.sequence).toBe(48));
    fireEvent.click(screen.getByTestId('causal-node-node:61'));
    await waitFor(() => expect(pending.at(-1)?.sequence).toBe(61));
    expect(pending[0].signal.aborted).toBe(true);
    const inspector = screen.getByRole('complementary', { name: 'Trajectory inspector' });
    fireEvent.click(within(inspector).getByRole('tab', { name: 'Context' }));

    const frame = (sequence: number): ContextFrame => ({
      id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: {}, delta: {}, after_state: {}, max_sequence: 78, request_artifact_ref: 'artifact:request',
    });
    await act(async () => {
      pending[1].resolve(frame(61));
      pending[0].resolve(frame(48));
    });

    expect(await within(inspector).findByText(/60 → 61/)).toBeVisible();
    expect(within(inspector).queryByText(/47 → 48/)).not.toBeInTheDocument();
  });

  it('does not render a late Context page after the user selects another run', async () => {
    const pending: Array<{
      runId: string;
      signal: AbortSignal;
      resolve: (page: ProjectionPage<ContextFrameSummary>) => void;
    }> = [];
    const getContextPage = vi.fn((runId: string, _request: unknown, signal?: AbortSignal) => new Promise<ProjectionPage<ContextFrameSummary>>((resolve) => {
      pending.push({ runId, signal: signal ?? new AbortController().signal, resolve });
    }));
    const getContextFrame = vi.fn(async (runId: string, sequence: number): Promise<ContextFrame> => ({
      id: `context:${runId}:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
      status: 'completed', unavailable_reason: null, source_sequence: sequence,
      before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
      before_state: { runId }, delta: {}, after_state: { runId }, max_sequence: sequence,
      request_artifact_ref: 'artifact:request',
    }));
    render(<App client={{ ...fixtureClient(), getContextPage, getContextFrame }} />);

    fireEvent.click(viewTab('Context'));
    await waitFor(() => expect(pending.at(-1)?.runId).toBe('analysis-test'));
    fireEvent.click(screen.getByRole('button', { name: /analysis-partial/i }));
    await waitFor(() => expect(pending.at(-1)?.runId).toBe('analysis-partial'));
    expect(pending[0].signal.aborted).toBe(true);

    const page = (analysisId: string, id: string, sequence: number): ProjectionPage<ContextFrameSummary> => ({
      analysis_id: analysisId,
      items: [{ id, source_sequence: sequence, before_revision: sequence - 1, after_revision: sequence, changed: true, request_input_available: true, event_kind: 'context-frame' }],
      older_cursor: null, newer_cursor: null, first_sequence: sequence, last_sequence: sequence,
      has_older: false, encoded_bytes: 100,
    });
    await act(async () => {
      pending[1].resolve(page('analysis-partial', 'context:fresh', 33));
      pending[0].resolve(page('analysis-test', 'context:stale', 77));
    });

    const fresh = await screen.findByRole('button', { name: /sequence 33/i });
    expect(screen.queryByRole('button', { name: /sequence 77/i })).not.toBeInTheDocument();
    expect(getContextFrame).not.toHaveBeenCalled();
    fireEvent.click(fresh);
    await waitFor(() => expect(getContextFrame).toHaveBeenCalledWith('analysis-partial', 33, expect.any(AbortSignal)));
    expect(getContextFrame).not.toHaveBeenCalledWith('analysis-test', 77, expect.anything());
    expect(await screen.findByText(/state at sequence 33/i)).toBeVisible();
    expect(screen.queryByText(/state at sequence 77/i)).not.toBeInTheDocument();
  });

  it('retains loaded evidence and retries exactly the failed opaque cursor', async () => {
    const evidencePage = (
      items: EvidenceRecord[], olderCursor: string | null, hasOlder: boolean,
    ): ProjectionPage<EvidenceRecord> => ({
      analysis_id: 'analysis-test', items, older_cursor: olderCursor, newer_cursor: null,
      first_sequence: items[0]?.producing_sequence ?? null,
      last_sequence: items.at(-1)?.producing_sequence ?? null,
      has_older: hasOlder, encoded_bytes: 100,
    });
    const getEvidencePage = vi.fn()
      .mockResolvedValueOnce(evidencePage([evidenceRecord('evidence:current', 61)], 'opaque/evidence-cursor', true))
      .mockRejectedValueOnce(new Error('older evidence unavailable'))
      .mockResolvedValueOnce(evidencePage([evidenceRecord('evidence:older', 17)], null, false))
      .mockResolvedValueOnce(evidencePage([evidenceRecord('evidence:current', 61)], 'opaque/evidence-cursor', true));
    render(<App client={{ ...fixtureClient(), getEvidencePage }} />);

    fireEvent.click(viewTab('Evidence'));
    expect((await screen.findAllByText('evidence:current')).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Load older evidence history' }));

    expect(await screen.findByText('older evidence unavailable')).toBeVisible();
    expect(screen.getAllByText('evidence:current').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Retry older evidence history' }));

    expect((await screen.findAllByText('evidence:older')).length).toBeGreaterThan(0);
    expect(getEvidencePage).toHaveBeenNthCalledWith(3, 'analysis-test', {
      cursor: 'opaque/evidence-cursor', filters: {},
    }, expect.any(AbortSignal));

    fireEvent.click(viewTab('Business'));
    fireEvent.click(viewTab('Evidence'));

    await waitFor(() => expect(getEvidencePage).toHaveBeenCalledTimes(4));
    expect((await screen.findAllByText('evidence:current')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('evidence:older').length).toBeGreaterThan(0);
  });

  it('ignores an out-of-order evidence index after switching runs', async () => {
    const pending: Array<{ runId: string; signal: AbortSignal; resolve: (index: EvidenceIndex) => void }> = [];
    const getEvidenceIndex = vi.fn((runId: string, signal?: AbortSignal) => new Promise<EvidenceIndex>((resolve) => {
      pending.push({ runId, signal: signal ?? new AbortController().signal, resolve });
    }));
    render(<App client={{ ...fixtureClient(), getEvidenceIndex }} />);

    fireEvent.click(viewTab('Evidence'));
    await waitFor(() => expect(pending.at(-1)?.runId).toBe('analysis-test'));
    fireEvent.click(screen.getByRole('button', { name: /analysis-partial/i }));
    await waitFor(() => expect(pending.at(-1)?.runId).toBe('analysis-partial'));
    expect(pending[0].signal.aborted).toBe(true);

    const index = (analysisId: string, reference: string): EvidenceIndex => ({
      analysis_id: analysisId,
      records: {
        [reference]: {
          id: `artifact:${reference}`, source: 'observed', source_sequences: [61], rule_id: null,
          status: 'completed', unavailable_reason: null, reference, kind: 'evidence',
          relative_path: `evidence/${reference}.json`, sha256: 'a'.repeat(64), verification_status: 'verified',
          producing_sequence: 61, consuming_sequences: [], turn_id: null, step_id: null,
          request_id: null, tool_call_id: null, result_id: null, evidence_id: reference, claim_id: null,
        },
      },
    });
    await act(async () => {
      pending[1].resolve(index('analysis-partial', 'evidence:fresh'));
      pending[0].resolve(index('analysis-test', 'evidence:stale'));
    });

    expect((await screen.findAllByText('evidence:fresh')).length).toBeGreaterThan(0);
    expect(screen.queryByText('evidence:stale')).not.toBeInTheDocument();
  });
});
