import { describe, expect, it } from 'vitest';
import type { BusinessCausalRow, BusinessProblemSummary } from './types';
import { prependBusinessRows, problemsFromBusinessRows } from './business';

const problem: BusinessProblemSummary = {
  id: 'business:analysis-test:turn-7',
  source: 'derived',
  rule_id: 'problem-grouping/v1',
  status: 'completed',
  unavailable_reason: null,
  turn_id: 'analysis-test-t007',
  title: 'Q7 · Line 17',
  first_sequence: 1,
  last_sequence: 100_000,
  node_count: 100_000,
};

function row(sequence: number): BusinessCausalRow {
  return {
    id: `${problem.id}:sequence:${sequence}`,
    source_sequence: sequence,
    problem,
    nodes: [{
      id: `business:analysis-test:${sequence}:tool`,
      source: 'observed',
      source_sequences: [sequence],
      rule_id: null,
      status: 'completed',
      unavailable_reason: null,
      kind: 'tool-action',
      title: `Tool ${sequence}`,
      detail: null,
      refs: [],
    }],
  };
}

describe('bounded business page adapter', () => {
  it('reconstructs stable group metadata from causal rows without an unbounded sequence list', () => {
    const problems = problemsFromBusinessRows([row(99_999), row(100_000)]);

    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatchObject({
      id: problem.id,
      source_sequences: [1, 100_000],
      source_sequence: 1,
      node_count: 100_000,
    });
    expect(problems[0].nodes.map((node) => node.source_sequence)).toEqual([99_999, 100_000]);
  });

  it('prepends exact older rows and de-duplicates a retried cursor by stable row id', () => {
    const current = [row(99_999), row(100_000)];
    const older = [row(99_997), row(99_998), row(99_999)];

    expect(prependBusinessRows(older, current).map((item) => item.source_sequence)).toEqual([
      99_997, 99_998, 99_999, 100_000,
    ]);
  });
});
