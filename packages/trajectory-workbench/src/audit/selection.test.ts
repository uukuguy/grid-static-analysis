import { describe, expect, it } from 'vitest';
import type { AgentEventRow, AgentTurn, BusinessProblem } from '../api/types';
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

  it('keeps a flat agent event as the selected inspector identity', () => {
    const row: AgentEventRow = {
      id: 'agent:analysis-test:tool-17',
      parent_id: 'agent:analysis-test:request-2',
      turn_id: 'analysis-t007',
      kind: 'tool',
      level: 4,
      source_sequence: 49,
      start_sequence: 47,
      end_sequence: 49,
      related_refs: ['evidence:line-17'],
      source: 'observed',
      status: 'completed',
      unavailable_reason: null,
      title: 'analysis.powerflow.ac.run',
      detail: null,
    };

    expect(resolveAuditSelection([problem], [], row.id, [row])).toMatchObject({
      problem: null,
      node: null,
      agentRow: row,
      sequence: 49,
      turnId: 'analysis-t007',
      artifactRefs: ['evidence:line-17'],
      agentTurn: null,
    });
  });
});
