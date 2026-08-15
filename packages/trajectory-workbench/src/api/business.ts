import type { BusinessCausalRow, BusinessNode, BusinessProblem } from './types';

/** Rebuild loaded problem groups from bounded causal rows and fixed metadata. */
export function problemsFromBusinessRows(rows: BusinessCausalRow[]): BusinessProblem[] {
  const grouped = new Map<string, { problem: BusinessProblem; nodeIds: Set<string> }>();
  for (const row of rows) {
    let entry = grouped.get(row.problem.id);
    if (!entry) {
      const sourceSequences = row.problem.first_sequence === row.problem.last_sequence
        ? [row.problem.first_sequence]
        : [row.problem.first_sequence, row.problem.last_sequence];
      entry = {
        problem: {
          id: row.problem.id,
          source: row.problem.source,
          source_sequences: sourceSequences,
          rule_id: row.problem.rule_id,
          status: row.problem.status,
          unavailable_reason: row.problem.unavailable_reason,
          source_sequence: row.problem.first_sequence,
          turn_id: row.problem.turn_id,
          title: row.problem.title,
          node_count: row.problem.node_count,
          nodes: [],
        },
        nodeIds: new Set<string>(),
      };
      grouped.set(row.problem.id, entry);
    }
    for (const node of row.nodes) {
      if (entry.nodeIds.has(node.id)) continue;
      entry.nodeIds.add(node.id);
      entry.problem.nodes.push({ ...node, source_sequence: row.source_sequence });
    }
  }
  return [...grouped.values()].map(({ problem }) => problem);
}

/** Older pages precede the loaded tail; a retry cannot duplicate stable rows. */
export function prependBusinessRows(
  older: BusinessCausalRow[],
  current: BusinessCausalRow[],
): BusinessCausalRow[] {
  const seen = new Set<string>();
  return [...older, ...current]
    .filter((row) => !seen.has(row.id) && (seen.add(row.id), true))
    .sort((left, right) => left.source_sequence - right.source_sequence);
}
