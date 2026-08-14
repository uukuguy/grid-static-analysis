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

    fireEvent.click(await screen.findByRole('button', { name: /Q7.*线路 17.*N-1/ }));

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
});
