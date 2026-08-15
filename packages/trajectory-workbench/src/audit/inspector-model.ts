import type { AgentStep, AgentTurn, AssistantResponse, ContextFrame, EvidenceIndex, EvidenceRecord, ModelRequest, ToolCall } from '../api/types';
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
  const execution = executionForSelection(args.selection, evidence, unavailable);

  if (!args.evidenceIndex) {
    unavailable.evidence = 'Evidence projection is not loaded for this selected event.';
  } else if (args.selection.artifactRefs.length === 0) {
    unavailable.evidence = 'No artifact references are recorded for this selected event.';
  } else if (evidence.length === 0) {
    unavailable.evidence = 'No evidence records match this selected event’s artifact references.';
  }

  return {
    selection: args.selection,
    evidence,
    context,
    execution,
    unavailable,
  };
}

interface ExecutionRelation {
  sequence: number;
  requestIds: Set<string>;
  toolCallIds: Set<string>;
  resultIds: Set<string>;
}

function executionForSelection(
  selection: AuditSelection,
  evidence: EvidenceRecord[],
  unavailable: Partial<Record<AuditPanel, string>>,
): AgentTurn | null {
  if (!selection.agentTurn) {
    unavailable.execution = 'Execution linkage is unavailable for this event.';
    return null;
  }

  const relation = executionRelation(selection, evidence);
  const steps = selection.agentTurn.steps
    .map((step) => scopeStep(step, relation))
    .filter((step): step is AgentStep => Boolean(step));

  if (steps.length === 0) {
    unavailable.execution = `Execution linkage is unavailable for sequence ${selection.sequence}: no typed execution relation is proven for the selected event.`;
    return null;
  }

  return { ...selection.agentTurn, steps };
}

function executionRelation(selection: AuditSelection, evidence: EvidenceRecord[]): ExecutionRelation {
  return {
    sequence: selection.sequence,
    requestIds: new Set(evidence.map((record) => record.request_id).filter(isPresent)),
    toolCallIds: new Set(evidence.map((record) => record.tool_call_id).filter(isPresent)),
    resultIds: new Set(evidence.map((record) => record.result_id).filter(isPresent)),
  };
}

function scopeStep(step: AgentStep, relation: ExecutionRelation): AgentStep | null {
  if (!step.request) return includesSequence(step.source_sequences, relation.sequence) ? step : null;
  const request = scopeRequest(step.request, relation);
  if (!request && !includesSequence(step.source_sequences, relation.sequence)) return null;
  return { ...step, request };
}

function scopeRequest(request: ModelRequest, relation: ExecutionRelation): ModelRequest | null {
  const requestDirect = relation.requestIds.has(request.request_id) || includesSequence(request.source_sequences, relation.sequence);
  const tools = request.tools.filter((tool) => toolMatches(tool, relation));
  const response = responseMatches(request.response, relation) || requestDirect ? request.response : null;
  if (!requestDirect && tools.length === 0 && !response) return null;
  return {
    ...request,
    retries: requestDirect ? request.retries : [],
    response,
    tools,
  };
}

function toolMatches(tool: ToolCall, relation: ExecutionRelation) {
  return relation.toolCallIds.has(tool.tool_call_id)
    || relation.resultIds.has(tool.id)
    || includesSequence(tool.source_sequences, relation.sequence)
    || tool.start_sequence === relation.sequence
    || tool.end_sequence === relation.sequence;
}

function responseMatches(response: AssistantResponse | null, relation: ExecutionRelation) {
  return Boolean(response && (
    relation.resultIds.has(response.id)
    || includesSequence(response.source_sequences, relation.sequence)
  ));
}

function includesSequence(sequences: number[], sequence: number) {
  return sequences.includes(sequence);
}

function isPresent(value: string | null): value is string {
  return value !== null && value.length > 0;
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
