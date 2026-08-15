import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ContextFrame, EvidenceIndex } from '../api/types';
import { ContextView } from './ContextView';
import { EvidenceView } from './EvidenceView';

const requestArtifact = 'artifact:request:7.2';

const nativeFrame: ContextFrame = {
  id: 'context:78', source: 'observed', source_sequences: [78], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 78, before_revision: 77, after_revision: 78, before_state_hash: 'before', after_state_hash: 'after', before_state: { revision: 77 }, delta: { added: 'result' }, after_state: { revision: 78 }, max_sequence: 90, request_artifact_ref: requestArtifact,
};

const legacyFrame: ContextFrame = { ...nativeFrame, request_artifact_ref: null, unavailable_reason: 'Legacy source did not capture model request input' };

const evidence: EvidenceIndex = { analysis_id: 'analysis-test', records: {
  'evidence:q7': { id: 'artifact:analysis-test:evidence:q7', source: 'observed', source_sequences: [75], rule_id: null, status: 'completed', unavailable_reason: null, reference: 'evidence:q7', kind: 'evidence', relative_path: 'evidence/analysis/q7.json', sha256: 'a'.repeat(64), verification_status: 'verified', producing_sequence: 75, consuming_sequences: [80], turn_id: null, step_id: null, request_id: null, tool_call_id: null, result_id: null, evidence_id: null, claim_id: null },
} };

describe('trajectory drill-down views', () => {
  afterEach(cleanup);
  it('shows exact before delta after and legacy unavailable request input', () => {
    const { rerender } = render(<ContextView frame={nativeFrame} onSelectSequence={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByRole('tab', { name: 'Before' })).toBeVisible();
    expect(within(screen.getByRole('region', { name: 'Model-visible request input' })).getByText(requestArtifact)).toBeVisible();
    fireEvent.click(within(screen.getByRole('region', { name: 'Context time travel' })).getByRole('tab', { name: 'Delta' }));
    expect(within(screen.getByRole('tabpanel')).getByText('added')).toBeVisible();
    rerender(<ContextView frame={legacyFrame} onSelectSequence={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByText('Legacy source did not capture model request input')).toBeVisible();
  });

  it('renders the exact typed evidence artifact projection', () => {
    const selectRef = vi.fn();
    render(<EvidenceView index={evidence} selectedRefs={['evidence:q7']} onSelectRef={selectRef} artifactUrl={(ref) => `/artifact/${ref}`} />);
    const record = screen.getByRole('button', { name: /evidence.*evidence:q7.*verified/i });
    fireEvent.click(record);
    expect(selectRef).toHaveBeenCalledWith('evidence:q7');
    expect(screen.getByRole('treegrid')).toHaveAccessibleName('Evidence artifacts');
    expect(screen.getByText('evidence/analysis/q7.json')).toBeVisible();
  });
});
