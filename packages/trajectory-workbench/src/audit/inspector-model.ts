import type { AgentTurn, ContextFrame, EvidenceIndex, EvidenceRecord } from '../api/types';
import type { AuditSelection } from './selection';

export type AuditPanel = 'overview' | 'evidence' | 'context' | 'execution';

export interface AuditInspectorModel {
  selection: AuditSelection;
  evidence: EvidenceRecord[];
  context: ContextFrame | null;
  execution: AgentTurn | null;
  unavailable: Partial<Record<AuditPanel, string>>;
}

export function buildAuditInspectorModel(args: {
  selection: AuditSelection;
  evidenceIndex: EvidenceIndex | null;
  context: ContextFrame | null;
}): AuditInspectorModel {
  const unavailable: Partial<Record<AuditPanel, string>> = {};
  const evidence = evidenceForSelection(args.selection, args.evidenceIndex);
  const context = contextForSelection(args.selection, args.context, unavailable);
  const execution = args.selection.agentTurn;

  if (!args.evidenceIndex) {
    unavailable.evidence = 'Evidence projection is not loaded for this selected event.';
  } else if (args.selection.artifactRefs.length === 0) {
    unavailable.evidence = 'No artifact references are recorded for this selected event.';
  } else if (evidence.length === 0) {
    unavailable.evidence = 'No evidence records match this selected event’s artifact references.';
  }

  if (!execution) {
    unavailable.execution = 'Execution linkage is unavailable for this event.';
  }

  return {
    selection: args.selection,
    evidence,
    context,
    execution,
    unavailable,
  };
}

function evidenceForSelection(selection: AuditSelection, evidenceIndex: EvidenceIndex | null) {
  if (!evidenceIndex) return [];
  const records = selection.artifactRefs
    .map((reference) => evidenceIndex.records[reference])
    .filter((record): record is EvidenceRecord => Boolean(record));
  return records;
}

function contextForSelection(
  selection: AuditSelection,
  context: ContextFrame | null,
  unavailable: Partial<Record<AuditPanel, string>>,
) {
  if (!context) {
    unavailable.context = `Context projection is not loaded for sequence ${selection.sequence}.`;
    return null;
  }
  if (context.source_sequence !== selection.sequence) {
    unavailable.context = `Context frame sequence ${context.source_sequence} does not match selected sequence ${selection.sequence}.`;
    return null;
  }
  return context;
}
