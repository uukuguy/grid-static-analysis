import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ContextFrame, EvidenceRecord } from '../api/types';
import { ContextView } from './ContextView';
import { EvidenceView } from './EvidenceView';

const requestArtifact = 'artifact:request:7.2';

const nativeFrame: ContextFrame = {
  id: 'context:78', source: 'observed', source_sequences: [78], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 78, before_revision: 77, after_revision: 78, before_state_hash: 'before', after_state_hash: 'after', before_state: { revision: 77 }, delta: { added: 'result' }, after_state: { revision: 78 }, max_sequence: 90, request_input_available: true, request_input_unavailable_reason: null, request_artifact_ref: requestArtifact,
};

const legacyFrame: ContextFrame = { ...nativeFrame, request_artifact_ref: null, unavailable_reason: 'Legacy source did not capture model request input', request_input_available: false, request_input_unavailable_reason: 'Legacy source did not capture model request input' };

const verifiedEvidence: EvidenceRecord = { id: 'artifact:analysis-test:evidence:q7', source: 'observed', source_sequences: [75], rule_id: null, status: 'completed', unavailable_reason: null, reference: 'evidence:q7', kind: 'evidence', relative_path: 'evidence/analysis/q7.json', sha256: 'a'.repeat(64), verification_status: 'verified', producing_sequence: 75, consuming_sequences: [80], turn_id: null, step_id: null, request_id: null, tool_call_id: null, result_id: null, evidence_id: null, claim_id: null };

const unavailableEvidence: EvidenceRecord = {
  ...verifiedEvidence,
  id: 'artifact:analysis-test:evidence:missing',
  reference: 'evidence:missing',
  relative_path: '',
  sha256: '',
  verification_status: 'unavailable',
  unavailable_reason: 'legacy run did not record a verified artifact',
};

describe('trajectory drill-down views', () => {
  afterEach(() => {
    cleanup();
    Reflect.deleteProperty(navigator, 'clipboard');
  });
  it('shows exact before delta after and legacy unavailable request input', () => {
    const { rerender } = render(<ContextView frame={nativeFrame} onSelectSequence={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByRole('tab', { name: 'Before' })).toBeVisible();
    expect(within(screen.getByRole('region', { name: 'Model-visible request input' })).getByText(requestArtifact)).toBeVisible();
    fireEvent.click(within(screen.getByRole('region', { name: 'Context time travel' })).getByRole('tab', { name: 'Delta' }));
    expect(within(screen.getByRole('tabpanel')).getByText('added')).toBeVisible();
    rerender(<ContextView frame={legacyFrame} onSelectSequence={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByText('Legacy source did not capture model request input')).toBeVisible();
  });

  it('disables preview and download for an unavailable evidence record with its reason', () => {
    const artifactUrl = vi.fn(() => '/must-not-be-created');
    render(<EvidenceView rows={[unavailableEvidence]} selectedRefs={[]} onSelectRef={vi.fn()} artifactUrl={artifactUrl} onSelectSequence={vi.fn()} />);

    expect(screen.getByText('legacy run did not record a verified artifact')).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /preview evidence:missing/i })).not.toBeInTheDocument();
    expect(artifactUrl).not.toHaveBeenCalled();
  });

  it('filters verified evidence, previews bounded JSON, and navigates recorded lineage', async () => {
    const selectRef = vi.fn();
    const selectSequence = vi.fn();
    const filtersChanged = vi.fn();
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const fetcher = vi.fn<typeof fetch>(async () => new Response('{"safe":true}', { headers: { 'Content-Type': 'application/json' } }));
    render(<EvidenceView
      rows={[verifiedEvidence]}
      filters={{}}
      onFiltersChange={filtersChanged}
      selectedRefs={['evidence:q7']}
      onSelectRef={selectRef}
      artifactUrl={(ref) => `/artifact/${ref}`}
      onSelectSequence={selectSequence}
      fetcher={fetcher}
    />);
    const record = screen.getByRole('button', { name: /evidence.*evidence:q7.*verified/i });
    fireEvent.click(record);
    expect(selectRef).toHaveBeenCalledWith('evidence:q7');
    expect(screen.getByRole('treegrid')).toHaveAccessibleName('Evidence artifacts');
    expect(screen.getByText('evidence/analysis/q7.json')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', '/artifact/evidence:q7');

    fireEvent.click(screen.getByRole('button', { name: 'Copy reference' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('evidence:q7'));
    expect(screen.getByRole('status')).toHaveTextContent('Copied evidence:q7');

    fireEvent.change(screen.getByLabelText('Evidence verification'), { target: { value: 'verified' } });
    expect(filtersChanged).toHaveBeenCalledWith({ verification_status: 'verified' });

    fireEvent.click(screen.getByRole('button', { name: 'Preview evidence:q7' }));
    expect(await screen.findByText('{"safe":true}')).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith('/artifact/evidence:q7', expect.objectContaining({ headers: expect.any(Headers) }));

    fireEvent.click(screen.getByRole('button', { name: 'Producer sequence 75' }));
    fireEvent.click(screen.getByRole('button', { name: 'Consumer sequence 80' }));
    await waitFor(() => expect(selectSequence.mock.calls).toEqual([[75], [80]]));
  });

  it('does not show a late preview after the run or filter identity changes', async () => {
    let resolvePreview!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>((resolve) => { resolvePreview = resolve; }));
    const props = {
      rows: [verifiedEvidence], selectedRefs: [], onSelectRef: vi.fn(), artifactUrl: (ref: string) => `/artifact/${ref}`,
      onSelectSequence: vi.fn(), fetcher,
    };
    const { rerender } = render(<EvidenceView {...props} previewIdentity="run-a" />);
    fireEvent.click(screen.getByRole('button', { name: 'Preview evidence:q7' }));
    expect(screen.getByRole('status')).toHaveTextContent('Loading bounded preview');

    rerender(<EvidenceView {...props} previewIdentity="run-b" />);
    await act(async () => {
      resolvePreview(new Response('{"stale":true}', { headers: { 'Content-Type': 'application/json' } }));
      await Promise.resolve();
    });

    expect(screen.queryByText('{"stale":true}')).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Artifact preview' })).not.toBeInTheDocument();
  });
});
