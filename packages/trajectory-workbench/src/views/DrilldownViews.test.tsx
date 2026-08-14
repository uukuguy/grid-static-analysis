import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AgentTurn, ContextFrame, EvidenceIndex } from '../api/types';
import { AgentView } from './AgentView';
import { ContextView } from './ContextView';
import { EvidenceView } from './EvidenceView';

const requestArtifact = 'artifact:request:7.2';

const agent: AgentTurn[] = [{
  id: 'agent:turn:7', source: 'observed', source_sequences: [70], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 70, turn_id: 'analysis-test-t007', ordinal: 7, steps: [{
    id: 'agent:step:7.2', source: 'observed', source_sequences: [71], rule_id: null, status: 'completed', unavailable_reason: null,
    step_id: '7.2', request: {
      id: 'agent:request:7.2', source: 'observed', source_sequences: [72], rule_id: null, status: 'completed', unavailable_reason: null,
      request_id: '7.2', artifact_ref: requestArtifact,
      retries: [{ id: 'agent:retry:7.2:1', source: 'observed', source_sequences: [73], rule_id: null, status: 'completed', unavailable_reason: null, attempt: 1, max_attempts: 2, delay_seconds: .2, message: 'temporary provider error' }],
      response: { id: 'agent:response:7.2', source: 'observed', source_sequences: [76], rule_id: null, status: 'completed', unavailable_reason: null, artifact_ref: 'artifact:response:7.2', stop_reason: 'end_turn', input_tokens: 500, output_tokens: 70, ttft_seconds: .82, duration_seconds: 1.42 },
      tools: [{ id: 'agent:tool:contingency', source: 'observed', source_sequences: [74, 75], rule_id: null, status: 'completed', unavailable_reason: null, tool_call_id: 'tool-7', capability: 'analysis.contingency.n_minus_one.run', start_sequence: 74, end_sequence: 75, artifact_ref: 'artifact:tool:7', ok: true, duration_seconds: 1.2 }],
    },
  }],
}];

const nativeFrame: ContextFrame = {
  id: 'context:78', source: 'observed', source_sequences: [78], rule_id: null, status: 'completed', unavailable_reason: null,
  source_sequence: 78, before_revision: 77, after_revision: 78, before_state_hash: 'before', after_state_hash: 'after', before_state: { revision: 77 }, delta: { added: 'result' }, after_state: { revision: 78 }, max_sequence: 90, request_artifact_ref: requestArtifact,
};

const legacyFrame: ContextFrame = { ...nativeFrame, request_artifact_ref: null, unavailable_reason: 'Legacy source did not capture model request input' };

const evidence: EvidenceIndex = { nodes: [
  { ref: 'claim:q7', type: 'claim', label: 'N-1 校核不通过', source: 'agent-declared', integrity: 'declared', producing_sequence: 80, consumers: 1, artifact_ref: null, unavailable_reason: null },
  { ref: 'evidence:q7', type: 'evidence', label: 'Contingency violations', source: 'observed', integrity: 'verified', producing_sequence: 75, consumers: 1, artifact_ref: 'artifact:evidence:q7', unavailable_reason: null },
], relations: [{ from_ref: 'claim:q7', to_ref: 'evidence:q7', relation: 'supported by' }] };

describe('trajectory drill-down views', () => {
  it('renders request timing retries and paired nested tools', () => {
    render(<AgentView trajectory={agent} selectedNodeId={null} onSelectNode={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByText('Request 7.2')).toBeVisible();
    expect(screen.getByText(/TTFT 0.82 s/)).toBeVisible();
    expect(screen.getByText(/Retry 1 of 2/)).toBeVisible();
    const tool = screen.getAllByRole('treeitem', { name: /analysis.contingency.n_minus_one.run.*completed/ }).find((item) => item.getAttribute('aria-level') === '4');
    expect(tool).toBeDefined();
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

  it('navigates evidence relationships in both directions with a keyboard treegrid', () => {
    const selectRef = vi.fn();
    render(<EvidenceView index={evidence} selectedRef="evidence:q7" onSelectRef={selectRef} artifactUrl={(ref) => `/artifact/${ref}`} />);
    const claim = screen.getByRole('button', { name: /Claim.*N-1 校核不通过/ });
    fireEvent.click(claim);
    expect(selectRef).toHaveBeenCalledWith('claim:q7');
    expect(screen.getByRole('treegrid')).toHaveAccessibleName('Evidence relationships');
    fireEvent.keyDown(claim, { key: 'ArrowDown' });
    expect(screen.getByRole('button', { name: /Evidence.*Contingency violations/ })).toHaveFocus();
  });
});
