import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BusinessProblem } from '../api/types';
import { initialWorkbenchState } from '../state/workbench';
import { BusinessView } from './BusinessView';

const problem: BusinessProblem = {
  id: 'business:q7', source: 'derived', source_sequences: [59], rule_id: 'business/v1',
  status: 'completed', unavailable_reason: null, source_sequence: 59, turn_id: 'analysis-test-t007',
  title: 'Q7 contingency', nodes: [{
    id: 'business:q7:claim', source: 'agent-declared', source_sequences: [60], rule_id: null,
    status: 'completed', unavailable_reason: null, source_sequence: 60, kind: 'claim',
    title: 'Contingency conclusion', detail: 'Line 17 overloads after outage.', refs: ['evidence:q7'],
  }],
};

describe('BusinessView', () => {
  afterEach(cleanup);
  it('filters nodes by text and preserves selected node state', async () => {
    const dispatch = vi.fn();
    const { rerender } = render(<BusinessView problems={[problem]} state={{ ...initialWorkbenchState, selectedNodeId: 'business:q7:claim' }} dispatch={dispatch} />);

    fireEvent.change(await screen.findByLabelText('Search business trajectory'), { target: { value: 'unmatched' } });

    expect(dispatch).toHaveBeenCalledWith({ type: 'search/changed', search: 'unmatched' });
    rerender(<BusinessView problems={[problem]} state={{ ...initialWorkbenchState, selectedNodeId: 'business:q7:claim', search: 'unmatched' }} dispatch={dispatch} />);
    expect(screen.queryByText('Contingency conclusion')).not.toBeInTheDocument();
  });

  it('folds a problem without clearing its selected node', async () => {
    const dispatch = vi.fn();
    render(<BusinessView problems={[problem]} state={{ ...initialWorkbenchState, selectedNodeId: 'business:q7:claim' }} dispatch={dispatch} />);

    fireEvent.click(await screen.findByRole('button', { name: /fold q7 contingency/i }));

    expect(dispatch).toHaveBeenCalledWith({ type: 'node/foldToggled', nodeId: 'business:q7' });
  });

  it('dispatches source and lifecycle filters without clearing selection', async () => {
    const dispatch = vi.fn();
    render(<BusinessView problems={[problem]} state={{ ...initialWorkbenchState, selectedNodeId: 'business:q7:claim' }} dispatch={dispatch} />);

    fireEvent.change(await screen.findByLabelText('Source filter'), { target: { value: 'agent-declared' } });
    fireEvent.change(screen.getByLabelText('Status filter'), { target: { value: 'completed' } });

    expect(dispatch).toHaveBeenCalledWith({ type: 'sourceFilter/changed', source: 'agent-declared' });
    expect(dispatch).toHaveBeenCalledWith({ type: 'statusFilter/changed', status: 'completed' });
  });

  it('keeps problem headers in the bounded virtual window at 100000 problems', async () => {
    const manyProblems = Array.from({ length: 100_000 }, (_, index) => ({
      ...problem, id: `business:${index}`, title: `Problem ${index}`, nodes: [],
    }));
    render(<BusinessView problems={manyProblems} state={initialWorkbenchState} dispatch={vi.fn()} />);

    expect(await screen.findByRole('button', { name: /fold problem 0/i })).toBeVisible();
    expect(screen.getAllByRole('button', { name: /fold|expand problem/i }).length).toBeLessThanOrEqual(120);
  });

  it('focuses a problem header that starts outside the mounted virtual window', async () => {
    const manyProblems = Array.from({ length: 80 }, (_, index) => ({
      ...problem,
      id: `business:${index}`,
      title: `Problem ${index}`,
      source_sequence: index + 1,
      source_sequences: [index + 1],
      nodes: [],
    }));

    render(<BusinessView
      problems={manyProblems}
      state={{
        ...initialWorkbenchState,
        focusedProblemId: 'business:60',
        selectedNodeId: 'business:0:claim',
      }}
      dispatch={vi.fn()}
    />);

    const focusedHeading = await screen.findByRole('heading', { name: 'Problem 60' });
    expect(focusedHeading).toHaveFocus();
    expect(screen.queryByRole('button', { name: /Agent-declared.*Contingency conclusion/i })).not.toBeInTheDocument();
  });
});
