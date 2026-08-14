import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, type TrajectoryApiClient } from '../api/client';
import type { BusinessProblem, ContextFrame, RunListResponse } from '../api/types';
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
    title: 'Q7 · 线路 17 N-1', nodes: [],
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
    getBusinessPage: async () => ({
      items: problems, older_cursor: null, newer_cursor: null, first_sequence: 59,
      last_sequence: 78, has_older: false, encoded_bytes: 100,
    }),
  };
}

describe('App shell', () => {
  afterEach(() => {
    cleanup();
    window.history.replaceState({}, '', '/');
  });
  it('renders the approved four-region hierarchy and business tab as selected', async () => {
    render(<App client={fixtureClient()} />);

    expect(await screen.findByRole('navigation', { name: 'Runs' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Run overview timeline' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Business' })).toHaveAttribute('aria-selected', 'true');
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
      .mockResolvedValueOnce({
        items: problems, older_cursor: null, newer_cursor: null, first_sequence: 59,
        last_sequence: 78, has_older: false, encoded_bytes: 100,
      });
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

  it('keyboard tabs move without a pointer', async () => {
    render(<App client={fixtureClient()} />);
    const business = await screen.findByRole('tab', { name: 'Business' });

    business.focus();
    fireEvent.keyDown(business, { key: 'ArrowRight' });

    expect(screen.getByRole('tab', { name: 'Agent' })).toHaveFocus();
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

  it('persists a selected trajectory item in the same-origin deep link', async () => {
    window.history.replaceState({}, '', '/');
    render(<App client={fixtureClient()} />);

    fireEvent.click(await screen.findByRole('button', { name: /Q7.*overview segment/i }));

    expect(new URLSearchParams(window.location.search).get('node')).toBe('analysis-test-t007');
  });

  it('resolves a nested business node deep link to its parent inspector and timeline turn', async () => {
    window.history.replaceState({}, '', '/?node=business:7:claim');
    render(<App client={{
      listRuns: async () => run,
      getBusinessPage: async () => ({ items: [nestedProblem], older_cursor: null, newer_cursor: null, first_sequence: 59, last_sequence: 78, has_older: false, encoded_bytes: 100 }),
    }} />);

    await screen.findByText('Nested conclusion');
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toHaveTextContent('business:7');
    expect(screen.getByRole('region', { name: 'Run overview timeline' })).toHaveAttribute('data-focused-turn', 'analysis-test-t007');
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
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText(/state at sequence 42/i)).toBeVisible();
  });

  it('ignores a malformed persisted context deep link without requesting a frame', async () => {
    const getContextFrame = vi.fn();
    window.history.replaceState({}, '', '/?node=context:not-a-sequence');
    render(<App client={{ ...fixtureClient(), getContextFrame }} />);

    await screen.findByRole('navigation', { name: 'Runs' });
    expect(getContextFrame).not.toHaveBeenCalled();
    expect(screen.getByRole('tab', { name: 'Business' })).toHaveAttribute('aria-selected', 'true');
  });

  it('fetches the older cursor once and prepends its problems before the current page', async () => {
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce({ items: [problems[0]], older_cursor: 'older-page', newer_cursor: null, first_sequence: 59, last_sequence: 78, has_older: true, encoded_bytes: 100 })
      .mockResolvedValueOnce({ items: [{ ...problems[0], id: 'business:6', title: 'Q6 · Earlier' }], older_cursor: null, newer_cursor: null, first_sequence: 1, last_sequence: 58, has_older: false, encoded_bytes: 100 });
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    await screen.findByRole('button', { name: /fold q7/i });
    fireEvent.click(screen.getByRole('button', { name: 'Load older history' }));

    await waitFor(() => expect(getBusinessPage).toHaveBeenLastCalledWith('analysis-test', 'older-page'));
    expect(await screen.findByText('Q6 · Earlier')).toBeVisible();
    expect(screen.getByText('Q6 · Earlier').compareDocumentPosition(screen.getByText('Q7 · 线路 17 N-1')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows unsupported when loading an older business cursor returns HTTP 501', async () => {
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce({ items: [problems[0]], older_cursor: 'older-page', newer_cursor: null, first_sequence: 59, last_sequence: 78, has_older: true, encoded_bytes: 100 })
      .mockRejectedValueOnce(new ApiError(501, 'unsupported', 'Older business history requires a newer workbench.'));
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Load older history' }));

    expect(await screen.findByTestId('state-unsupported')).toHaveTextContent('Older business history requires a newer workbench.');
    expect(getBusinessPage).toHaveBeenLastCalledWith('analysis-test', 'older-page');
  });

  it('retries a failed older business cursor instead of the initial page', async () => {
    const olderProblem = { ...problems[0], id: 'business:6', title: 'Q6 · Earlier' };
    const getBusinessPage = vi.fn()
      .mockResolvedValueOnce({ items: [problems[0]], older_cursor: 'older-page', newer_cursor: null, first_sequence: 59, last_sequence: 78, has_older: true, encoded_bytes: 100 })
      .mockRejectedValueOnce(new Error('older history unavailable'))
      .mockResolvedValueOnce({ items: [olderProblem], older_cursor: null, newer_cursor: null, first_sequence: 1, last_sequence: 58, has_older: false, encoded_bytes: 100 });
    render(<App client={{ listRuns: async () => run, getBusinessPage }} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Load older history' }));
    expect(await screen.findByTestId('state-network-error')).toHaveTextContent('older history unavailable');

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Q6 · Earlier')).toBeVisible();
    expect(getBusinessPage).toHaveBeenNthCalledWith(3, 'analysis-test', 'older-page');
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
    const inspectorTab = await screen.findByRole('tab', { name: 'Identity' });

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

    fireEvent.click(await screen.findByRole('tab', { name: 'Context' }));
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
    fireEvent.click(screen.getByRole('tab', { name: 'Context' }));
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

    fireEvent.click(await screen.findByRole('tab', { name: 'Context' }));
    await screen.findByText(/state at sequence 78/i);
    fireEvent.click(screen.getByRole('button', { name: /Q7.*overview segment/i }));

    await waitFor(() => expect(getContextFrame).toHaveBeenLastCalledWith('analysis-test', 59, expect.any(AbortSignal)));
    expect(await screen.findByText(/state at sequence 59/i)).toBeVisible();
  });
});
