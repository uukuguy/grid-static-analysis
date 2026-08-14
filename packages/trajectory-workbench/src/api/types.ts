/** Types mirror the read-only trajectory API's JSON response envelopes. */
export type NodeSource = 'observed' | 'derived' | 'agent-declared';
export type LifecycleStatus = 'running' | 'completed' | 'failed' | 'interrupted' | 'unavailable';

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

export interface BusinessNode extends ProjectionNode {
  source_sequence: number;
  kind: string;
  title: string;
  detail: string | null;
  refs: string[];
}

export interface BusinessProblem extends ProjectionNode {
  source_sequence: number;
  turn_id: string;
  title: string;
  nodes: BusinessNode[];
}

export interface ContextFrame extends ProjectionNode {
  source_sequence: number;
  before_revision: number;
  after_revision: number;
  before_state_hash: string;
  after_state_hash: string;
  before_state: Record<string, unknown>;
  delta: Record<string, unknown>;
  after_state: Record<string, unknown>;
  request_artifact_ref: string | null;
  max_sequence: number;
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
