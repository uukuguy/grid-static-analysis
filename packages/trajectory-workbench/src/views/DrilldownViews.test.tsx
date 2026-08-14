import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
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

const evidence: EvidenceIndex = { analysis_id: 'analysis-test', records: {
  'evidence:q7': { id: 'artifact:analysis-test:evidence:q7', source: 'observed', source_sequences: [75], rule_id: null, status: 'completed', unavailable_reason: null, reference: 'evidence:q7', kind: 'evidence', relative_path: 'evidence/analysis/q7.json', sha256: 'a'.repeat(64), verification_status: 'verified', producing_sequence: 75, consuming_sequences: [80], turn_id: null, step_id: null, request_id: null, tool_call_id: null, result_id: null, evidence_id: null, claim_id: null },
} };

describe('trajectory drill-down views', () => {
  afterEach(cleanup);
  it('renders request timing retries and paired nested tools', () => {
    render(<AgentView trajectory={agent} selectedNodeId={null} onSelectNode={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);
    expect(screen.getByText('Request 7.2')).toBeVisible();
    expect(screen.getByText(/TTFT 0.82 s/)).toBeVisible();
    expect(screen.getByText(/Retry 1 of 2/)).toBeVisible();
    const tool = screen.getAllByRole('treeitem', { name: /analysis.contingency.n_minus_one.run.*completed/ }).find((item) => item.getAttribute('aria-level') === '4');
    expect(tool).toBeDefined();
  });

  it('uses roving focus and standard tree expansion keys for the agent hierarchy', () => {
    const selectNode = vi.fn();
    render(<AgentView trajectory={agent} selectedNodeId={null} onSelectNode={selectNode} artifactUrl={(ref) => `/artifact/${ref}`} />);
    const turn = screen.getByRole('treeitem', { name: /Turn 7.*analysis-test-t007/ });
    turn.focus();
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    expect(turn).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    expect(screen.getByRole('treeitem', { name: /Step 7.2/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('treeitem', { name: /Step 7.2/ }), { key: 'End' });
    expect(screen.getByRole('treeitem', { name: /Assistant response/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('treeitem', { name: /Assistant response/ }), { key: 'Home' });
    expect(turn).toHaveFocus();
    fireEvent.keyDown(turn, { key: 'Enter' });
    expect(selectNode).toHaveBeenCalledWith('agent:turn:7');
    fireEvent.keyDown(turn, { key: 'ArrowLeft' });
    expect(turn).toHaveAttribute('aria-expanded', 'false');
  });

  it('makes the root tab stop available when agent turns arrive after an empty render', () => {
    const { rerender } = render(<AgentView trajectory={[]} selectedNodeId={null} onSelectNode={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);

    rerender(<AgentView trajectory={agent} selectedNodeId={null} onSelectNode={vi.fn()} artifactUrl={(ref) => `/artifact/${ref}`} />);

    const turn = screen.getByRole('treeitem', { name: /Turn 7.*analysis-test-t007/ });
    expect(turn).toHaveAttribute('tabindex', '0');
    turn.focus();
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    fireEvent.keyDown(turn, { key: 'ArrowRight' });
    expect(screen.getByRole('treeitem', { name: /Step 7.2/ })).toHaveFocus();
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

  it('renders the exact typed evidence artifact projection', () => {
    const selectRef = vi.fn();
    render(<EvidenceView index={evidence} selectedRef="evidence:q7" onSelectRef={selectRef} artifactUrl={(ref) => `/artifact/${ref}`} />);
    const record = screen.getByRole('button', { name: /evidence.*evidence:q7.*verified/i });
    fireEvent.click(record);
    expect(selectRef).toHaveBeenCalledWith('evidence:q7');
    expect(screen.getByRole('treegrid')).toHaveAccessibleName('Evidence artifacts');
    expect(screen.getByText('evidence/analysis/q7.json')).toBeVisible();
  });
});
