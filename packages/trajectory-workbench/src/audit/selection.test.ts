import { describe, expect, it } from 'vitest';
import type { AgentTurn, BusinessProblem } from '../api/types';
import { resolveAuditSelection } from './selection';

const problem: BusinessProblem = {
  id: 'problem:q7',
  source: 'derived',
  source_sequences: [41, 48],
  rule_id: 'business/v1',
  status: 'completed',
  unavailable_reason: null,
  source_sequence: 41,
  turn_id: 'analysis-t007',
  title: 'Q7 · Line 17 N-1',
  nodes: [{
    id: 'claim:7',
    source: 'agent-declared',
    source_sequences: [48],
    rule_id: null,
    status: 'completed',
    unavailable_reason: null,
    source_sequence: 48,
    kind: 'claim',
    title: 'Line 17 overload conclusion',
    detail: null,
    refs: ['evidence:line-17', 'result:contingency-17', 'evidence:line-17'],
  }],
};

const turn: AgentTurn = {
  id: 'turn:q7',
  source: 'observed',
  source_sequences: [39, 48],
  rule_id: null,
  status: 'completed',
  unavailable_reason: null,
  source_sequence: 39,
  turn_id: 'analysis-t007',
  ordinal: 7,
  steps: [],
};

describe('resolveAuditSelection', () => {
  it('resolves a nested claim to its exact sequence, refs, and owning turn', () => {
    expect(resolveAuditSelection([problem], [turn], 'claim:7')).toMatchObject({
      problem,
      node: problem.nodes[0],
      sequence: 48,
      turnId: 'analysis-t007',
      artifactRefs: ['evidence:line-17', 'result:contingency-17'],
      agentTurn: turn,
    });
  });
});
