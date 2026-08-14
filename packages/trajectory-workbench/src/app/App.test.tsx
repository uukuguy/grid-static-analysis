import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { TrajectoryApiClient } from '../api/client';
import type { BusinessProblem, RunListResponse } from '../api/types';
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
  afterEach(cleanup);
  it('renders the approved four-region hierarchy and business tab as selected', async () => {
    render(<App client={fixtureClient()} />);

    expect(await screen.findByRole('navigation', { name: 'Runs' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Run overview timeline' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Business' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('complementary', { name: 'Trajectory inspector' })).toBeVisible();
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
});
