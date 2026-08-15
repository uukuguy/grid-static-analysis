import type { AgentEventRow, AgentTurn, BusinessNode, BusinessProblem } from '../api/types';

export interface AuditSelection {
  problem: BusinessProblem | null;
  node: BusinessNode | null;
  agentRow: AgentEventRow | null;
  sequence: number;
  turnId: string;
  artifactRefs: string[];
  agentTurn: AgentTurn | null;
}

export function resolveAuditSelection(
  problems: BusinessProblem[],
  agentTurns: AgentTurn[],
  selectedNodeId: string | null,
  agentRows: AgentEventRow[] = [],
): AuditSelection | null {
  if (!selectedNodeId) return null;

  const agentRow = agentRows.find((row) => row.id === selectedNodeId) ?? null;
  if (agentRow) {
    return {
      problem: null,
      node: null,
      agentRow,
      sequence: agentRow.source_sequence,
      turnId: agentRow.turn_id,
      artifactRefs: uniqueRefs(agentRow.related_refs),
      agentTurn: agentTurns.find((turn) => turn.turn_id === agentRow.turn_id) ?? null,
    };
  }

  for (const problem of problems) {
    const node = problem.nodes.find((candidate) => candidate.id === selectedNodeId) ?? null;
    if (!node && problem.id !== selectedNodeId && problem.turn_id !== selectedNodeId) continue;

    return {
      problem,
      node,
      agentRow: null,
      sequence: node?.source_sequence ?? problem.source_sequence,
      turnId: problem.turn_id,
      artifactRefs: uniqueRefs(node ? node.refs : problem.nodes.flatMap((item) => item.refs)),
      agentTurn: agentTurns.find((turn) => turn.turn_id === problem.turn_id) ?? null,
    };
  }

  return null;
}

function uniqueRefs(refs: string[]) {
  return [...new Set(refs)];
}
