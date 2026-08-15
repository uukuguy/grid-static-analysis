import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ContextFrame, ContextFrameSummary } from '../api/types';
import { ContextView } from './ContextView';

const summaries: ContextFrameSummary[] = [
  { id: 'context:40', source_sequence: 40, before_revision: 10, after_revision: 11, changed: true, request_input_available: true, request_input_unavailable_reason: null, event_kind: 'tool-result' },
  { id: 'context:50', source_sequence: 50, before_revision: 11, after_revision: 12, changed: true, request_input_available: false, request_input_unavailable_reason: 'request input digest mismatch', event_kind: 'model-request' },
];

function frame(sequence: number, before: ContextFrame['before_state'], after: ContextFrame['after_state']): ContextFrame {
  return {
    id: `context:${sequence}`, source: 'observed', source_sequences: [sequence], rule_id: null,
    status: 'completed', unavailable_reason: null, source_sequence: sequence,
    before_revision: sequence - 1, after_revision: sequence, before_state_hash: 'before', after_state_hash: 'after',
    before_state: before, delta: {}, after_state: after, max_sequence: 90,
    request_input_available: true, request_input_unavailable_reason: null,
    request_artifact_ref: 'artifact:request',
  };
}

const baseProps = {
  summaries,
  filters: {},
  onFiltersChange: vi.fn(),
  hasOlder: true,
  olderState: 'idle' as const,
  olderError: null,
  onLoadOlder: vi.fn(),
  onRetryOlder: vi.fn(),
  selectedSequence: null,
  frame: null,
  detailState: 'idle' as const,
  detailError: null,
  onRetryDetail: vi.fn(),
  onSelectSequence: vi.fn(),
  artifactUrl: (ref: string) => `/artifact/${ref}`,
  comparisonIdentity: 'analysis-test:base',
};

describe('ContextView', () => {
  afterEach(cleanup);

  it('renders only summary facts until a loaded frame is selected', () => {
    const onSelectSequence = vi.fn();
    render(<ContextView {...baseProps} onSelectSequence={onSelectSequence} />);

    expect(screen.getByRole('list', { name: 'Loaded context frames' })).toBeVisible();
    expect(screen.getByRole('button', { name: /sequence 40.*tool-result/i })).toBeVisible();
    expect(screen.getByText('request input digest mismatch')).toBeVisible();
    expect(screen.queryByText(/Authoritative state at sequence/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /sequence 40.*tool-result/i }));
    expect(onSelectSequence).toHaveBeenCalledWith(40);
  });

  it('suppresses an unverified request input ref and renders its persisted reason', () => {
    const artifactUrl = vi.fn((ref: string) => `/artifact/${ref}`);
    const unverified = {
      ...frame(50, {}, {}),
      request_input_available: false,
      request_input_unavailable_reason: 'request input digest mismatch',
    } as ContextFrame & {
      request_input_available: boolean;
      request_input_unavailable_reason: string;
    };

    render(<ContextView {...baseProps} selectedSequence={50} frame={unverified} detailState="ready" artifactUrl={artifactUrl} />);

    expect(screen.getAllByText('request input digest mismatch').length).toBeGreaterThan(0);
    expect(screen.queryByRole('link', { name: 'artifact:request' })).not.toBeInTheDocument();
    expect(artifactUrl).not.toHaveBeenCalled();
  });

  it('filters summaries and exposes exact older-page retry controls', () => {
    const onFiltersChange = vi.fn();
    const onRetryOlder = vi.fn();
    const { rerender } = render(<ContextView {...baseProps} onFiltersChange={onFiltersChange} />);

    fireEvent.change(screen.getByLabelText('Context changed state'), { target: { value: 'true' } });
    expect(onFiltersChange).toHaveBeenCalledWith({ changed: true });
    fireEvent.click(screen.getByRole('button', { name: 'Load older context history' }));
    expect(baseProps.onLoadOlder).toHaveBeenCalledOnce();

    rerender(<ContextView {...baseProps} olderState="failed" olderError="opaque cursor failed" onRetryOlder={onRetryOlder} />);
    expect(screen.getByRole('alert')).toHaveTextContent('opaque cursor failed');
    fireEvent.click(screen.getByRole('button', { name: 'Retry older context history' }));
    expect(onRetryOlder).toHaveBeenCalledOnce();
  });

  it('moves previous and next only among loaded summary sequences', () => {
    const onSelectSequence = vi.fn();
    render(<ContextView {...baseProps} selectedSequence={50} frame={frame(50, {}, {})} onSelectSequence={onSelectSequence} />);

    fireEvent.click(screen.getByRole('button', { name: 'Previous loaded frame' }));
    expect(onSelectSequence).toHaveBeenCalledWith(40);
    expect(screen.getByRole('button', { name: 'Next loaded frame' })).toBeDisabled();
  });

  it('pins two fetched authoritative frames and compares their recorded after states', () => {
    const first = frame(40, { limits: { x: 0 } }, { limits: { x: 1 } });
    const second = frame(50, { limits: { x: 1 } }, { limits: { x: 2 }, mode: 'n1' });
    const { rerender } = render(<ContextView {...baseProps} selectedSequence={40} frame={first} detailState="ready" />);

    fireEvent.click(screen.getByRole('button', { name: 'Pin sequence 40 as frame A' }));
    rerender(<ContextView {...baseProps} selectedSequence={50} frame={second} detailState="ready" />);
    fireEvent.click(screen.getByRole('button', { name: 'Pin sequence 50 as frame B' }));

    const comparison = screen.getByRole('region', { name: 'Pinned frame comparison' });
    expect(comparison).toHaveTextContent('A · sequence 40');
    expect(comparison).toHaveTextContent('B · sequence 50');
    expect(within(comparison).getByText('mode')).toBeVisible();
    expect(within(comparison).getByText('limits.x')).toBeVisible();
  });

  it('uses structured collapsible state as primary detail and raw JSON as secondary disclosure', () => {
    render(<ContextView {...baseProps} selectedSequence={40} frame={frame(40, { nested: { value: 1 } }, {})} detailState="ready" />);

    expect(screen.getByRole('tree', { name: 'Before recorded context state' })).toBeVisible();
    expect(screen.getByText('nested')).toBeVisible();
    expect(screen.queryByText(/"nested":/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Raw recorded JSON'));
    expect(screen.getByText(/"nested":/)).toBeVisible();
  });
});
