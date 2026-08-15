import { describe, expect, it } from 'vitest';
import type { AgentTurn, BusinessProblem, ContextFrame, EvidenceIndex } from '../api/types';
import type { AuditSelection } from './selection';
import { buildAuditInspectorModel } from './inspector-model';

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
    refs: ['evidence:line-17', 'result:pf-17'],
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
  agentRow: null,
  sequence: 61,
  turnId: 'turn-7',
  artifactRefs: ['evidence:line-17', 'result:pf-17'],
  agentTurn: turn,
};

const matchingContext: ContextFrame = {
  id: 'context:61',
  source: 'observed',
  source_sequences: [61],
  rule_id: null,
  status: 'completed',
  unavailable_reason: null,
  source_sequence: 61,
  before_revision: 12,
  after_revision: 13,
  before_state_hash: 'before-hash',
  after_state_hash: 'after-hash',
  before_state: { phase: 'before' },
  delta: { selected: 'line-17' },
  after_state: { phase: 'after' },
  max_sequence: 99,
  request_input_available: true,
  request_input_unavailable_reason: null,
  request_artifact_ref: 'request:turn-7',
};

const evidenceIndex: EvidenceIndex = {
  analysis_id: 'analysis-test',
  records: {
    'evidence:line-17': {
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
    },
    'unrelated:artifact': {
      id: 'record:other',
      source: 'observed',
      source_sequences: [55],
      rule_id: null,
      status: 'completed',
      unavailable_reason: null,
      reference: 'unrelated:artifact',
      kind: 'sidecar',
      relative_path: 'artifacts/other.json',
      sha256: 'b'.repeat(64),
      verification_status: 'verified',
      producing_sequence: 55,
      consuming_sequences: [],
      turn_id: null,
      step_id: null,
      request_id: null,
      tool_call_id: null,
      result_id: null,
      evidence_id: null,
      claim_id: null,
    },
  },
};

describe('buildAuditInspectorModel', () => {
  it('filters evidence to selected artifact refs and accepts only the exact context sequence', () => {
    const model = buildAuditInspectorModel({ selection, evidenceIndex, context: matchingContext });

    expect(model.selection).toBe(selection);
    expect(model.evidence.map((record) => record.reference)).toEqual(['evidence:line-17']);
    expect(model.context).toBe(matchingContext);
    expect(model.execution).toBeNull();
    expect(model.unavailable.execution).toMatch(/no typed execution relation/i);
  });

  it('does not reuse a context frame from another sequence', () => {
    const model = buildAuditInspectorModel({
      selection,
      evidenceIndex,
      context: { ...matchingContext, id: 'context:60', source_sequence: 60 },
    });

    expect(model.context).toBeNull();
    expect(model.unavailable.context).toMatch(/sequence 61/i);
  });

  it('scopes execution to typed evidence relations and excludes unrelated same-turn requests', () => {
    const turnWithMixedRequests: AgentTurn = {
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
          artifact_ref: 'raw:request-related',
          retries: [],
          response: null,
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
            artifact_ref: 'raw:tool-related',
            ok: true,
            duration_seconds: 1.25,
          }, {
            id: 'tool:unrelated',
            source: 'observed',
            source_sequences: [58],
            rule_id: null,
            status: 'completed',
            unavailable_reason: null,
            tool_call_id: 'tool-unrelated',
            capability: 'grid.unrelated',
            start_sequence: 58,
            end_sequence: 59,
            artifact_ref: 'raw:tool-unrelated',
            ok: true,
            duration_seconds: 2,
          }],
        },
      }, {
        id: 'step:unrelated',
        source: 'observed',
        source_sequences: [55],
        rule_id: null,
        status: 'completed',
        unavailable_reason: null,
        step_id: 'step-unrelated',
        request: {
          id: 'request:unrelated',
          source: 'observed',
          source_sequences: [55],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          request_id: 'request-unrelated',
          artifact_ref: 'raw:request-unrelated',
          retries: [],
          response: null,
          tools: [],
        },
      }],
    };

    const model = buildAuditInspectorModel({
      selection: { ...selection, agentTurn: turnWithMixedRequests },
      evidenceIndex,
      context: matchingContext,
    });

    expect(model.execution?.steps.map((step) => step.step_id)).toEqual(['step-related']);
    expect(model.execution?.steps[0].request?.request_id).toBe('request-2');
    expect(model.execution?.steps[0].request?.tools.map((tool) => tool.tool_call_id)).toEqual(['tool-17']);
    expect(JSON.stringify(model.execution)).not.toContain('request-unrelated');
    expect(JSON.stringify(model.execution)).not.toContain('tool-unrelated');
  });

  it('marks execution unavailable when raw artifacts are the only possible relation', () => {
    const rawArtifactOnlyTurn: AgentTurn = {
      ...turn,
      steps: [{
        id: 'step:raw-only',
        source: 'observed',
        source_sequences: [52],
        rule_id: null,
        status: 'completed',
        unavailable_reason: null,
        step_id: 'step-raw-only',
        request: {
          id: 'request:raw-only',
          source: 'observed',
          source_sequences: [52],
          rule_id: null,
          status: 'completed',
          unavailable_reason: null,
          request_id: 'request-raw-only',
          artifact_ref: 'evidence:line-17',
          retries: [],
          response: null,
          tools: [],
        },
      }],
    };
    const rawArtifactOnlyEvidence: EvidenceIndex = {
      analysis_id: 'analysis-test',
      records: {
        'evidence:line-17': {
          ...evidenceIndex.records['evidence:line-17'],
          request_id: null,
          tool_call_id: null,
          result_id: null,
          claim_id: null,
          producing_sequence: null,
          source_sequences: [52],
        },
      },
    };

    const model = buildAuditInspectorModel({
      selection: { ...selection, agentTurn: rawArtifactOnlyTurn },
      evidenceIndex: rawArtifactOnlyEvidence,
      context: matchingContext,
    });

    expect(model.execution).toBeNull();
    expect(model.unavailable.execution).toMatch(/typed execution relation/i);
  });
});
