import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentTurn, BusinessProblem, ContextFrame, ExecutionSlice } from '../../api/types';
import type { AuditInspectorModel } from '../../audit/inspector-model';
import type { AuditSelection } from '../../audit/selection';
import { AuditInspector } from './AuditInspector';

const problem: BusinessProblem = {
  id: 'problem:q7',
  source: 'derived',
  source_sequences: [41, 61],
  rule_id: 'business/v1',
  status: 'completed',
  unavailable_reason: null,
  source_sequence: 41,
  turn_id: 'turn-7',
  title: 'Q7 · Line 17 N-1',
  nodes: [{
    id: 'claim:7',
    source: 'agent-declared',
    source_sequences: [61],
    rule_id: null,
    status: 'completed',
    unavailable_reason: null,
    source_sequence: 61,
    kind: 'claim',
    title: 'Line 17 overload conclusion',
    detail: 'Line 17 overloads after the contingency.',
    refs: ['evidence:line-17'],
  }],
};

const turn: AgentTurn = {
  id: 'agent-turn:7',
  source: 'observed',
  source_sequences: [45, 61],
  rule_id: null,
  status: 'completed',
  unavailable_reason: null,
  source_sequence: 45,
  turn_id: 'turn-7',
  ordinal: 7,
  steps: [],
};

const selection: AuditSelection = {
  problem,
  node: problem.nodes[0],
  sequence: 61,
  turnId: 'turn-7',
  artifactRefs: ['evidence:line-17'],
  agentTurn: turn,
};

const legacyContext: ContextFrame = {
  id: 'context:61',
  source: 'observed',
  source_sequences: [61],
  rule_id: null,
  status: 'completed',
  unavailable_reason: 'Request input is unavailable for legacy imported runs.',
  source_sequence: 61,
  before_revision: 12,
  after_revision: 13,
  before_state_hash: 'before-hash',
  after_state_hash: 'after-hash',
  before_state: { selected: 'before' },
  delta: { change: 'line-17' },
  after_state: { selected: 'after' },
  max_sequence: 99,
  request_artifact_ref: null,
};

afterEach(cleanup);

describe('AuditInspector', () => {
  it('renders four audit tabs and shows legacy request unavailability without fabricating input', () => {
    const model: AuditInspectorModel = {
      selection,
      evidence: [],
      context: legacyContext,
      execution: turn,
      unavailable: {},
    };

    render(<AuditInspector model={model} artifactUrl={(ref) => `/artifact/${ref}`} onSelectSequence={vi.fn()} />);

    expect(screen.getByRole('tab', { name: 'Overview' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Evidence' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Context' })).toBeVisible();
    expect(screen.getByRole('tab', { name: 'Execution' })).toBeVisible();

    fireEvent.click(screen.getByRole('tab', { name: 'Context' }));

    expect(screen.getByText(/request input is unavailable for legacy imported runs/i)).toBeVisible();
    expect(screen.queryByText(/raw sidecar/i)).not.toBeInTheDocument();
  });

  it('uses producer sequence buttons instead of inert JSON placeholders', () => {
    const onSelectSequence = vi.fn();
    const model: AuditInspectorModel = {
      selection,
      evidence: [{
        id: 'record:line-17',
        source: 'observed',
        source_sequences: [47],
        rule_id: null,
        status: 'completed',
        unavailable_reason: null,
        reference: 'evidence:line-17',
        kind: 'tool-result',
        relative_path: 'artifacts/line-17.json',
        sha256: 'a'.repeat(64),
        verification_status: 'verified',
        producing_sequence: 47,
        consuming_sequences: [61],
        turn_id: 'turn-7',
        step_id: 'step-2',
        request_id: 'request-2',
        tool_call_id: 'tool-17',
        result_id: 'result-17',
        evidence_id: null,
        claim_id: 'claim:7',
      }],
      context: null,
      execution: turn,
      unavailable: { context: 'Context projection is not loaded.' },
    };

    render(<AuditInspector model={model} artifactUrl={(ref) => `/artifact/${ref}`} onSelectSequence={onSelectSequence} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
    fireEvent.click(screen.getByRole('button', { name: /go to sequence 47/i }));

    expect(onSelectSequence).toHaveBeenCalledWith(47);
    expect(screen.queryByText(/"node"/)).not.toBeInTheDocument();
  });

  it('does not link raw execution artifacts while showing permitted public summaries', () => {
    const artifactUrl = vi.fn((ref: string) => `/artifact/${ref}`);
    const model: AuditInspectorModel = {
      selection,
      evidence: [],
      context: null,
      execution: {
        ...turn,
        steps: [{
          id: 'step:related',
          source: 'observed',
          source_sequences: [52],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          step_id: 'step-related',
          request: {
            id: 'request:related',
            source: 'observed',
            source_sequences: [52],
            rule_id: null,
            status: 'completed',
            unavailable_reason: null,
            request_id: 'request-2',
            artifact_ref: 'raw:request-input',
            retries: [{
              id: 'retry:1',
              source: 'observed',
              source_sequences: [53],
              rule_id: null,
              status: 'completed',
              unavailable_reason: null,
              attempt: 1,
              max_attempts: 2,
              delay_seconds: 0.5,
              message: 'retryable failure',
            }],
            response: {
              id: 'response:related',
              source: 'observed',
              source_sequences: [61],
              rule_id: null,
              status: 'completed',
              unavailable_reason: null,
              artifact_ref: 'raw:assistant-response',
              stop_reason: 'stop',
              input_tokens: 120,
              output_tokens: 45,
              ttft_seconds: 0.2,
              duration_seconds: 1.4,
            },
            tools: [{
              id: 'tool:related',
              source: 'observed',
              source_sequences: [47],
              rule_id: null,
              status: 'completed',
              unavailable_reason: null,
              tool_call_id: 'tool-17',
              capability: 'grid.analyze',
              start_sequence: 47,
              end_sequence: 48,
              artifact_ref: 'raw:tool-result',
              ok: true,
              duration_seconds: 1.25,
            }],
          },
        }],
      },
      unavailable: { context: 'Context projection is not loaded.' },
    };

    render(<AuditInspector model={model} artifactUrl={artifactUrl} onSelectSequence={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Execution' }));

    expect(screen.getByText('request-2')).toBeVisible();
    expect(screen.getByText('grid.analyze')).toBeVisible();
    expect(screen.getByText(/completed · duration 1.25 seconds/i)).toBeVisible();
    expect(screen.getByText(/tokens 120 in \/ 45 out/i)).toBeVisible();
    expect(screen.getByText(/raw request input is unavailable/i)).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(artifactUrl).not.toHaveBeenCalledWith(expect.stringMatching(/^raw:/));
  });

  it('renders explicit execution slice unavailability without falling back to the selected turn', () => {
    const model: AuditInspectorModel = {
      selection,
      evidence: [],
      context: null,
      execution: turn,
      unavailable: {},
    };
    const executionSlice: ExecutionSlice = {
      analysis_id: 'analysis-test',
      source_sequence: 61,
      turn: null,
      unavailable_reason: 'no durable execution linkage is recorded',
    };

    render(<AuditInspector model={model} executionSlice={executionSlice} artifactUrl={() => '#'} onSelectSequence={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Execution' }));

    expect(screen.getByText('no durable execution linkage is recorded')).toBeVisible();
    expect(screen.queryByText('turn-7')).not.toBeInTheDocument();
  });

  it('renders only execution-slice descendants linked to the selected sequence', () => {
    const model: AuditInspectorModel = {
      selection,
      evidence: [],
      context: null,
      execution: null,
      unavailable: {},
    };
    const executionSlice: ExecutionSlice = {
      analysis_id: 'analysis-test',
      source_sequence: 61,
      unavailable_reason: null,
      turn: {
        ...turn,
        steps: [
          {
            id: 'step:related',
            source: 'observed',
            source_sequences: [60],
            rule_id: null,
            status: 'completed',
            unavailable_reason: null,
            step_id: 'step-related',
            request: {
              id: 'request:related',
              source: 'observed',
              source_sequences: [60],
              rule_id: null,
              status: 'completed',
              unavailable_reason: null,
              request_id: 'request-related',
              artifact_ref: 'artifact:request',
              retries: [],
              response: {
                id: 'response:related',
                source: 'observed',
                source_sequences: [61],
                rule_id: null,
                status: 'completed',
                unavailable_reason: null,
                artifact_ref: 'artifact:response',
                stop_reason: 'stop',
                input_tokens: 120,
                output_tokens: 45,
                ttft_seconds: 0.2,
                duration_seconds: 1.4,
              },
              tools: [
                {
                  id: 'tool:related',
                  source: 'observed',
                  source_sequences: [61],
                  rule_id: null,
                  status: 'completed',
                  unavailable_reason: null,
                  tool_call_id: 'tool-related',
                  capability: 'grid.analyze',
                  start_sequence: 61,
                  end_sequence: null,
                  artifact_ref: 'artifact:tool',
                  ok: true,
                  duration_seconds: 1.25,
                },
                {
                  id: 'tool:unrelated',
                  source: 'observed',
                  source_sequences: [62],
                  rule_id: null,
                  status: 'completed',
                  unavailable_reason: null,
                  tool_call_id: 'tool-unrelated',
                  capability: 'provider_payload.unrelated',
                  start_sequence: 62,
                  end_sequence: null,
                  artifact_ref: '/private/turns/provider_payload.json',
                  ok: true,
                  duration_seconds: 0.1,
                },
              ],
            },
          },
          {
            id: 'step:unrelated',
            source: 'observed',
            source_sequences: [63],
            rule_id: null,
            status: 'completed',
            unavailable_reason: null,
            step_id: 'step-unrelated',
            request: {
              id: 'request:unrelated',
              source: 'observed',
              source_sequences: [64],
              rule_id: null,
              status: 'completed',
              unavailable_reason: null,
              request_id: 'request-unrelated',
              artifact_ref: '/private/turns/provider_payload.json',
              retries: [],
              response: null,
              tools: [],
            },
          },
        ],
      },
    };

    render(<AuditInspector model={model} executionSlice={executionSlice} artifactUrl={() => '#'} onSelectSequence={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Execution' }));

    expect(screen.getByText('request-related')).toBeVisible();
    expect(screen.getByText('grid.analyze')).toBeVisible();
    expect(screen.queryByText('request-unrelated')).not.toBeInTheDocument();
    expect(screen.queryByText('provider_payload.unrelated')).not.toBeInTheDocument();
    expect(screen.queryByText('/private/turns/provider_payload.json')).not.toBeInTheDocument();
  });
});
