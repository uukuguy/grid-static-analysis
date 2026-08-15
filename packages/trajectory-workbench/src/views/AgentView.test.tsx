import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentEventRow, AgentPageFilters } from '../api/types';
import { AgentView } from './AgentView';

const turnId = 'analysis-test-t007';

function row(overrides: Partial<AgentEventRow> & Pick<AgentEventRow, 'id' | 'kind' | 'level' | 'source_sequence' | 'title'>): AgentEventRow {
  return {
    parent_id: null,
    turn_id: turnId,
    source: 'observed',
    status: 'completed',
    unavailable_reason: null,
    detail: null,
    start_sequence: null,
    end_sequence: null,
    related_refs: [],
    ...overrides,
  };
}

const hierarchy: AgentEventRow[] = [
  row({ id: 'turn:7', kind: 'turn', level: 1, source_sequence: 70, title: 'Turn 7' }),
  row({ id: 'step:7', parent_id: 'turn:7', kind: 'step', level: 2, source_sequence: 71, title: 'Step 7.1' }),
  row({ id: 'request:7', parent_id: 'step:7', kind: 'request', level: 3, source_sequence: 72, title: 'Request 7.1' }),
  row({ id: 'tool:7', parent_id: 'request:7', kind: 'tool', level: 4, source_sequence: 74, title: 'analysis.contingency.n_minus_one.run' }),
  row({ id: 'response:7', parent_id: 'request:7', kind: 'response', level: 4, source_sequence: 76, title: 'Assistant response', detail: '70 output tokens' }),
];

const defaults = {
  filters: {} as AgentPageFilters,
  onFiltersChange: vi.fn(),
  hasOlder: false,
  olderState: 'idle' as const,
  olderError: null,
  onLoadOlder: vi.fn(),
  onRetryOlder: vi.fn(),
  selectedNodeId: null,
  businessSequences: [] as number[],
  onSelectNode: vi.fn(),
  onSelectSequence: vi.fn(),
};

describe('AgentView', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows a truncated parent marker rather than inventing a missing tree parent', () => {
    render(<AgentView {...defaults} rows={[hierarchy[3]]} />);

    expect(screen.getByRole('treegrid', { name: 'Agent execution events' })).toBeVisible();
    expect(screen.getByRole('row', { name: /analysis.contingency.*completed.*sequence 74/i })).toHaveAttribute('aria-level', '4');
    expect(screen.getByText('Parent request:7 is outside loaded history.')).toBeVisible();
    expect(screen.queryByText('Request 7.1')).not.toBeInTheDocument();
  });

  it('attaches a parent arriving on an older page without changing the child row identity', () => {
    const { rerender } = render(<AgentView {...defaults} rows={[hierarchy[3]]} />);
    const child = screen.getByTestId('agent-event-tool:7');

    rerender(<AgentView {...defaults} rows={hierarchy} />);

    expect(screen.getByTestId('agent-event-tool:7')).toBe(child);
    expect(screen.queryByText('Parent request:7 is outside loaded history.')).not.toBeInTheDocument();
  });

  it('dispatches allow-listed turn, kind, status, capability, and query filters', () => {
    const onFiltersChange = vi.fn();
    render(<AgentView {...defaults} rows={hierarchy} onFiltersChange={onFiltersChange} />);

    fireEvent.change(screen.getByLabelText('Agent turn ID'), { target: { value: turnId } });
    fireEvent.change(screen.getByLabelText('Agent event kind'), { target: { value: 'tool' } });
    fireEvent.change(screen.getByLabelText('Agent lifecycle status'), { target: { value: 'failed' } });
    fireEvent.change(screen.getByLabelText('Agent capability'), { target: { value: 'gridctl' } });
    fireEvent.change(screen.getByLabelText('Search agent events'), { target: { value: 'contingency' } });

    expect(onFiltersChange).toHaveBeenCalledWith({ turn_id: turnId });
    expect(onFiltersChange).toHaveBeenCalledWith({ kind: 'tool' });
    expect(onFiltersChange).toHaveBeenCalledWith({ status: 'failed' });
    expect(onFiltersChange).toHaveBeenCalledWith({ capability: 'gridctl' });
    expect(onFiltersChange).toHaveBeenCalledWith({ q: 'contingency' });
  });

  it('retains rows and retries a failed older page', () => {
    const onRetryOlder = vi.fn();
    render(<AgentView {...defaults} rows={hierarchy} hasOlder olderState="failed" olderError="opaque cursor unavailable" onRetryOlder={onRetryOlder} />);

    expect(screen.getByText('Turn 7')).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('opaque cursor unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry older agent history' }));

    expect(onRetryOlder).toHaveBeenCalledTimes(1);
  });

  it('selects a tool without replacing its identity with a sequence node', () => {
    const onSelectNode = vi.fn();
    const onSelectSequence = vi.fn();
    render(<AgentView {...defaults} rows={hierarchy} onSelectNode={onSelectNode} onSelectSequence={onSelectSequence} />);

    fireEvent.click(screen.getByRole('row', { name: /analysis.contingency.*completed.*sequence 74/i }));

    expect(onSelectNode).toHaveBeenCalledWith('tool:7');
    expect(onSelectSequence).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('No recorded Business relationship exists at sequence 74.');
  });

  it('offers only the recorded tool completion relation for Business navigation', () => {
    const onSelectSequence = vi.fn();
    const completedTool = row({
      id: 'tool:recorded-relation',
      parent_id: 'request:7',
      kind: 'tool',
      level: 4,
      source_sequence: 49,
      start_sequence: 48,
      end_sequence: 49,
      title: 'analysis.powerflow.ac.run',
    });
    render(<AgentView
      {...defaults}
      rows={[completedTool]}
      businessSequences={[48, 49]}
      onSelectSequence={onSelectSequence}
    />);

    fireEvent.click(screen.getByRole('row', { name: /analysis.powerflow.ac.run/i }));
    expect(onSelectSequence).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Go to recorded Business sequence 49' }));
    expect(onSelectSequence).toHaveBeenCalledWith(49);
    expect(onSelectSequence).not.toHaveBeenCalledWith(48);
  });

  it('supports roving treegrid focus, expansion, and activation keys', () => {
    const onSelectNode = vi.fn();
    render(<AgentView {...defaults} rows={hierarchy} onSelectNode={onSelectNode} />);
    const turn = screen.getByRole('row', { name: /Turn 7.*completed.*sequence 70/i });

    turn.focus();
    fireEvent.keyDown(turn, { key: 'ArrowLeft' });
    expect(turn).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    expect(turn).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    expect(screen.getByRole('row', { name: /Step 7.1/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('row', { name: /Step 7.1/ }), { key: 'End' });
    expect(screen.getByRole('row', { name: /Assistant response/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('row', { name: /Assistant response/ }), { key: 'Home' });
    expect(turn).toHaveFocus();
    fireEvent.keyDown(turn, { key: 'Enter' });
    expect(onSelectNode).toHaveBeenCalledWith('turn:7');
  });

  it('keeps a 100k flat page inside the bounded virtual DOM window', () => {
    const rows = Array.from({ length: 100_000 }, (_, index) => row({
      id: `tool:${index}`,
      parent_id: 'request:outside-page',
      kind: 'tool',
      level: 4,
      source_sequence: index + 1,
      title: `Tool ${index + 1}`,
    }));

    render(<AgentView {...defaults} rows={rows} />);

    expect(screen.getAllByRole('row').length).toBeLessThanOrEqual(120);
  });

  it('renders only public row fields even if an untyped transport adds private payload fields', () => {
    const unsafe = {
      ...hierarchy[3],
      artifact_ref: '/private/provider/request.json',
      provider_payload: 'secret-provider-body',
    } as AgentEventRow;

    render(<AgentView {...defaults} rows={[unsafe]} />);

    const renderedRow = screen.getByTestId('agent-event-tool:7');
    expect(screen.queryByText('/private/provider/request.json')).not.toBeInTheDocument();
    expect(screen.queryByText('secret-provider-body')).not.toBeInTheDocument();
    expect(renderedRow).not.toHaveTextContent(turnId);
    expect(renderedRow).not.toHaveTextContent('observed');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
