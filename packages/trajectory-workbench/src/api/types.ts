/** Types mirror the read-only trajectory API's JSON response envelopes. */
export type NodeSource = 'observed' | 'derived' | 'agent-declared';
export type LifecycleStatus = 'running' | 'completed' | 'failed' | 'interrupted' | 'unavailable';

/** JSON values emitted by the API after Pydantic serializes context mappings. */
export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject { [key: string]: JsonValue; }

/** Backend `ContextFrame` state mappings and typed state deltas. */
export type ContextState = JsonObject;
export type ContextDelta = JsonObject;

export interface ProjectionPage<T> {
  items: T[];
  older_cursor: string | null;
  newer_cursor: null;
  first_sequence: number | null;
  last_sequence: number | null;
  has_older: boolean;
  encoded_bytes: number;
}

export interface ProjectionNode {
  id: string;
  source: NodeSource;
  source_sequences: number[];
  rule_id: string | null;
  status: LifecycleStatus;
  unavailable_reason: string | null;
}

export interface AgentRetry extends ProjectionNode {
  attempt: number;
  max_attempts: number;
  delay_seconds: number | null;
  message: string | null;
}

export interface AssistantResponse extends ProjectionNode {
  artifact_ref: string | null;
  stop_reason: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  ttft_seconds: number | null;
  duration_seconds: number | null;
}

export interface ToolCall extends ProjectionNode {
  tool_call_id: string;
  capability: string;
  start_sequence: number;
  end_sequence: number | null;
  artifact_ref: string | null;
  ok: boolean | null;
  duration_seconds: number | null;
}

export interface ModelRequest extends ProjectionNode {
  request_id: string;
  artifact_ref: string | null;
  retries: AgentRetry[];
  response: AssistantResponse | null;
  tools: ToolCall[];
}

export interface AgentStep extends ProjectionNode {
  step_id: string;
  request: ModelRequest | null;
}

export interface AgentTurn extends ProjectionNode {
  source_sequence: number;
  turn_id: string;
  ordinal: number | null;
  steps: AgentStep[];
}

export interface ExecutionSlice {
  analysis_id: string;
  source_sequence: number;
  turn: AgentTurn | null;
  unavailable_reason: string | null;
}

export interface BusinessNode extends ProjectionNode {
  source_sequence: number;
  kind: string;
  title: string;
  detail: string | null;
  refs: string[];
  contextRevision?: number | null;
}

export interface BusinessProblem extends ProjectionNode {
  source_sequence: number;
  turn_id: string;
  title: string;
  nodes: BusinessNode[];
}

interface ContextFrameBase extends ProjectionNode {
  source_sequence: number;
  before_revision: number;
  after_revision: number;
  before_state_hash: string;
  after_state_hash: string;
  before_state: ContextState;
  delta: ContextDelta;
  after_state: ContextState;
  max_sequence: number;
}

/** A native frame has the immutable request input captured by the backend. */
export interface ContextFrameWithRequest extends ContextFrameBase {
  request_artifact_ref: string;
}

/** Legacy frames must state why the exact model input cannot be shown. */
export interface ContextFrameWithoutRequest extends ContextFrameBase {
  request_artifact_ref: null;
  unavailable_reason: string;
}

export type ContextFrame = ContextFrameWithRequest | ContextFrameWithoutRequest;

/** Exact immutable artifact projection returned by the read-only evidence endpoint. */
export interface EvidenceRecord {
  id: string;
  source: NodeSource;
  source_sequences: number[];
  rule_id: string | null;
  status: LifecycleStatus;
  unavailable_reason: string | null;
  reference: string;
  kind: string;
  relative_path: string;
  sha256: string;
  verification_status: string;
  producing_sequence: number | null;
  consuming_sequences: number[];
  turn_id: string | null;
  step_id: string | null;
  request_id: string | null;
  tool_call_id: string | null;
  result_id: string | null;
  evidence_id: string | null;
  claim_id: string | null;
}

export interface EvidenceIndex {
  analysis_id: string;
  records: Record<string, EvidenceRecord>;
}

export interface RunSummary {
  analysis_id: string;
  status: string;
  source_kind: string;
  started_at: string | null;
  turn_count: number;
  last_sequence: number | null;
  replay_trusted_through: number | null;
  diagnostic: string | null;
}

export interface RunListResponse { items: RunSummary[]; }
export interface ApiErrorResponse { code: string; message: string; }
