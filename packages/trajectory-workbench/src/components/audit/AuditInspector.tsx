import type { KeyboardEvent } from 'react';
import { useState } from 'react';
import type { AgentStep, AgentTurn, AssistantResponse, ContextFrame, EvidenceRecord, ExecutionSlice, JsonValue, ModelRequest, ProjectionNode, ToolCall } from '../../api/types';
import type { AuditInspectorModel, AuditPanel } from '../../audit/inspector-model';
import { AsyncState, type AsyncStateName } from '../common/AsyncState';
import { SourceBadge } from '../common/SourceBadge';

const tabs: { id: AuditPanel; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'context', label: 'Context' },
  { id: 'execution', label: 'Execution' },
];

interface AuditInspectorProps {
  model: AuditInspectorModel | null;
  executionSlice?: ExecutionSlice | null;
  artifactUrl: (ref: string) => string;
  onSelectSequence?: (sequence: number) => void;
  panelStates?: Partial<Record<AuditPanel, AsyncStateName>>;
  panelDiagnostics?: Partial<Record<AuditPanel, string | null>>;
  onRetryPanel?: (panel: AuditPanel) => void;
  runStatus?: string | null;
  runDiagnostic?: string | null;
}

export function AuditInspector({
  model,
  executionSlice,
  artifactUrl,
  onSelectSequence = () => undefined,
  panelStates = {},
  panelDiagnostics = {},
  onRetryPanel = () => undefined,
  runStatus = null,
  runDiagnostic = null,
}: AuditInspectorProps) {
  const [active, setActive] = useState<AuditPanel>('overview');
  const activeIndex = tabs.findIndex((tab) => tab.id === active);
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    setActive(tabs[next].id);
    document.getElementById(`audit-inspector-tab-${tabs[next].id}`)?.focus();
  };

  return <div className="inspector-content audit-inspector">
    {runStatus === 'partial' ? <InspectorRunNotice kind="partial" diagnostic={runDiagnostic} /> : null}
    <div role="tablist" aria-label="Audit inspector details" className="inspector-tabs">
      {tabs.map((tab, index) => <button
        key={tab.id}
        id={`audit-inspector-tab-${tab.id}`}
        type="button"
        role="tab"
        aria-selected={active === tab.id}
        aria-controls={`audit-inspector-panel-${tab.id}`}
        tabIndex={active === tab.id ? 0 : -1}
        onClick={() => setActive(tab.id)}
        onKeyDown={(event) => onKeyDown(event, index)}
      >
        {tab.label}
      </button>)}
    </div>
    <section id={`audit-inspector-panel-${active}`} role="tabpanel" aria-label={tabs[activeIndex]?.label ?? 'Audit inspector'} className="inspector-panel audit-inspector-panel">
      {runStatus === 'corrupt'
        ? <InspectorRunNotice kind="corrupt" diagnostic={runDiagnostic} />
        : <PanelContent
          active={active}
          model={model}
          executionSlice={executionSlice}
          artifactUrl={artifactUrl}
          onSelectSequence={onSelectSequence}
          state={panelStates[active] ?? 'ready'}
          diagnostic={panelDiagnostics[active]}
          onRetry={() => onRetryPanel(active)}
        />}
    </section>
  </div>;
}

function InspectorRunNotice({ kind, diagnostic }: { kind: 'partial' | 'corrupt'; diagnostic?: string | null }) {
  const title = kind === 'partial' ? 'Run is partial' : 'Run data is corrupt';
  const detail = kind === 'partial' ? 'Only the recorded portion of this run is available.' : 'This run cannot be safely displayed.';
  return <section className={`async-state state-${kind}`} role="status" aria-live="polite">
    <h2>{title}</h2>
    <p>{diagnostic ?? detail}</p>
  </section>;
}

function PanelContent({
  active,
  model,
  executionSlice,
  artifactUrl,
  onSelectSequence,
  state,
  diagnostic,
  onRetry,
}: {
  active: AuditPanel;
  model: AuditInspectorModel | null;
  executionSlice?: ExecutionSlice | null;
  artifactUrl: (ref: string) => string;
  onSelectSequence: (sequence: number) => void;
  state: AsyncStateName;
  diagnostic?: string | null;
  onRetry: () => void;
}) {
  if (!model) return <p>Select a turn or node to inspect its recorded details.</p>;
  if (active !== 'overview' && state !== 'ready' && state !== 'idle') {
    return <AsyncState state={state} diagnostic={diagnostic} onRetry={onRetry} />;
  }
  if (active === 'overview') return <OverviewPanel model={model} onSelectSequence={onSelectSequence} />;
  if (active === 'evidence') return <EvidencePanel model={model} artifactUrl={artifactUrl} onSelectSequence={onSelectSequence} />;
  if (active === 'context') return <ContextPanel model={model} artifactUrl={artifactUrl} onSelectSequence={onSelectSequence} />;
  return <ExecutionPanel model={model} executionSlice={executionSlice} />;
}

function OverviewPanel({ model, onSelectSequence }: { model: AuditInspectorModel; onSelectSequence: (sequence: number) => void }) {
  const selected = model.selection.node ?? model.selection.problem;
  const node = model.selection.node;
  return <div className="audit-panel-stack">
    <dl>
      <dt>Selected ID</dt><dd>{selected.id}</dd>
      <dt>Turn</dt><dd>{model.selection.turnId}</dd>
      <dt>Sequence</dt><dd><button type="button" className="sequence-link" onClick={() => onSelectSequence(model.selection.sequence)}>Go to sequence {model.selection.sequence}</button></dd>
      <dt>Source</dt><dd><SourceBadge source={selected.source} /></dd>
      <dt>Status</dt><dd>{selected.status}</dd>
      <dt>Problem</dt><dd>{model.selection.problem.title}</dd>
      {node ? <><dt>Kind</dt><dd>{node.kind}</dd><dt>Title</dt><dd>{node.title}</dd></> : null}
      {node?.detail ? <><dt>Detail</dt><dd>{node.detail}</dd></> : null}
      <dt>Parent</dt><dd>{node ? model.selection.problem.id : 'Run business trajectory'}</dd>
      <dt>Children</dt><dd>{node ? 'No child business nodes are recorded.' : `${model.selection.problem.nodes.length} business nodes`}</dd>
    </dl>
    {selected.unavailable_reason ? <p className="unavailable">{selected.unavailable_reason}</p> : null}
  </div>;
}

function EvidencePanel({ model, artifactUrl, onSelectSequence }: { model: AuditInspectorModel; artifactUrl: (ref: string) => string; onSelectSequence: (sequence: number) => void }) {
  if (model.unavailable.evidence) return <p className="unavailable">{model.unavailable.evidence}</p>;
  return <div className="audit-card-list">
    {model.evidence.map((record) => <EvidenceCard key={record.reference} record={record} artifactUrl={artifactUrl} onSelectSequence={onSelectSequence} />)}
  </div>;
}

function EvidenceCard({ record, artifactUrl, onSelectSequence }: { record: EvidenceRecord; artifactUrl: (ref: string) => string; onSelectSequence: (sequence: number) => void }) {
  return <article className="audit-card">
    <h3>{record.kind} · {record.reference}</h3>
    <dl>
      <dt>Verification</dt><dd>{record.verification_status}{record.unavailable_reason ? ` · ${record.unavailable_reason}` : ''}</dd>
      <dt>Digest</dt><dd><code>{record.sha256.slice(0, 12)}</code></dd>
      <dt>Path</dt><dd>{record.relative_path}</dd>
      <dt>Producer</dt><dd>{record.producing_sequence === null ? 'Unavailable' : <button type="button" className="sequence-link" onClick={() => onSelectSequence(record.producing_sequence!)}>Go to sequence {record.producing_sequence}</button>}</dd>
      <dt>Consumers</dt><dd>{record.consuming_sequences.length ? record.consuming_sequences.map((sequence) => <button key={sequence} type="button" className="sequence-link" onClick={() => onSelectSequence(sequence)}>Go to sequence {sequence}</button>) : 'No recorded consumers'}</dd>
      <dt>Artifact</dt><dd><a href={artifactUrl(record.reference)} download>{record.reference}</a></dd>
    </dl>
  </article>;
}

function ContextPanel({ model, artifactUrl, onSelectSequence }: { model: AuditInspectorModel; artifactUrl: (ref: string) => string; onSelectSequence: (sequence: number) => void }) {
  const frame = model.context;
  if (!frame) return <p className="unavailable">{model.unavailable.context ?? 'Context projection is unavailable for this event.'}</p>;
  return <div className="audit-panel-stack">
    <dl>
      <dt>Sequence</dt><dd><button type="button" className="sequence-link" onClick={() => onSelectSequence(frame.source_sequence)}>Go to sequence {frame.source_sequence}</button></dd>
      <dt>Revisions</dt><dd>{frame.before_revision} → {frame.after_revision}</dd>
      <dt>State hashes</dt><dd>{frame.before_state_hash} → {frame.after_state_hash}</dd>
    </dl>
    <StateBlock title="Before" value={frame.before_state} />
    <StateBlock title="Delta" value={frame.delta} />
    <StateBlock title="After" value={frame.after_state} />
    <section className="request-input" aria-label="Model-visible request input">
      <h3>Model-visible request input</h3>
      {frame.request_artifact_ref
        ? <a href={artifactUrl(frame.request_artifact_ref)} download>{frame.request_artifact_ref}</a>
        : <p className="unavailable">{frame.unavailable_reason || 'Request input is unavailable for this event.'}</p>}
    </section>
  </div>;
}

function StateBlock({ title, value }: { title: string; value: JsonValue }) {
  return <section className="audit-state-block">
    <h3>{title}</h3>
    <pre className="json-document">{JSON.stringify(value, null, 2)}</pre>
  </section>;
}

function ExecutionPanel({ model, executionSlice }: { model: AuditInspectorModel; executionSlice?: ExecutionSlice | null }) {
  const staleSlice = executionSlice !== undefined && executionSlice !== null && executionSlice.source_sequence !== model.selection.sequence;
  const rawTurn = executionSlice === undefined ? model.execution : staleSlice ? null : executionSlice?.turn ?? null;
  const turn = executionSlice === undefined ? rawTurn : rawTurn ? scopeTurn(rawTurn, model.selection.sequence) : null;
  const unavailable = executionSlice === undefined
    ? model.unavailable.execution
    : staleSlice
      ? `Execution slice sequence ${executionSlice.source_sequence} does not match selected sequence ${model.selection.sequence}.`
      : executionSlice?.unavailable_reason ?? `Execution slice is not loaded for sequence ${model.selection.sequence}.`;
  if (!turn) return <p className="unavailable">{unavailable ?? 'Execution linkage is unavailable for this event.'}</p>;
  return <div className="audit-panel-stack">
    <dl>
      <dt>Turn ID</dt><dd>{turn.turn_id}</dd>
      <dt>Ordinal</dt><dd>{turn.ordinal ?? 'Unavailable'}</dd>
      <dt>Sequence</dt><dd>{sourceSequence(turn)}</dd>
      <dt>Source</dt><dd><SourceBadge source={turn.source} /></dd>
      <dt>Status</dt><dd>{turn.status}{turn.unavailable_reason ? ` · ${turn.unavailable_reason}` : ''}</dd>
    </dl>
    {turn.steps.length ? turn.steps.map((step) => <StepCard key={step.id} step={step} />) : <p className="unavailable">No public request/tool entries are recorded for this selected turn.</p>}
  </div>;
}

function sourceSequence(turn: AgentTurn) {
  return turn.source_sequence ?? Math.max(...turn.source_sequences);
}

function scopeTurn(turn: AgentTurn, sequence: number): AgentTurn | null {
  const steps = turn.steps
    .map((step) => scopeStepForSequence(step, sequence))
    .filter((step): step is AgentStep => Boolean(step));
  if (!nodeMatchesSequence(turn, sequence) && steps.length === 0) return null;
  return { ...turn, steps };
}

function scopeStepForSequence(step: AgentStep, sequence: number): AgentStep | null {
  const request = step.request ? scopeRequestForSequence(step.request, sequence) : null;
  if (!nodeMatchesSequence(step, sequence) && !request) return null;
  return { ...step, request };
}

function scopeRequestForSequence(request: ModelRequest, sequence: number): ModelRequest | null {
  const retries = request.retries.filter((retry) => nodeMatchesSequence(retry, sequence));
  const response = request.response && nodeMatchesSequence(request.response, sequence) ? request.response : null;
  const tools = request.tools.filter((tool) => nodeMatchesSequence(tool, sequence));
  if (!nodeMatchesSequence(request, sequence) && retries.length === 0 && !response && tools.length === 0) return null;
  return { ...request, retries, response, tools };
}

function nodeMatchesSequence(node: ProjectionNode, sequence: number) {
  return node.source_sequences.includes(sequence) || node.id.split(':').includes(String(sequence));
}

function StepCard({ step }: { step: AgentStep }) {
  return <article className="audit-card">
    <h3>Step {step.step_id}</h3>
    {step.request ? <RequestDetails request={step.request} /> : <p className="unavailable">{step.unavailable_reason ?? 'No model request is recorded for this step.'}</p>}
  </article>;
}

function RequestDetails({ request }: { request: ModelRequest }) {
  return <div className="audit-panel-stack">
    <dl>
      <dt>Request</dt><dd>{request.request_id}</dd>
      <dt>Input</dt><dd>{request.artifact_ref ? <span className="unavailable">Raw request input is unavailable in the execution inspector.</span> : <span className="unavailable">Request input artifact unavailable.</span>}</dd>
      <dt>Status</dt><dd>{request.status}{request.unavailable_reason ? ` · ${request.unavailable_reason}` : ''}</dd>
    </dl>
    {request.retries.length ? <section><h4>Retries</h4>{request.retries.map((retry) => <p key={retry.id}>Attempt {retry.attempt} of {retry.max_attempts}; delay {retry.delay_seconds ?? 'unavailable'} seconds{retry.message ? ` · ${retry.message}` : ''}</p>)}</section> : null}
    {request.tools.length ? <section><h4>Tools</h4>{request.tools.map((tool) => <ToolSummary key={tool.id} tool={tool} />)}</section> : null}
    {request.response ? <ResponseSummary response={request.response} /> : null}
  </div>;
}

function ToolSummary({ tool }: { tool: ToolCall }) {
  return <article className="audit-subcard">
    <h5>{tool.capability}</h5>
    <p>Sequence {tool.start_sequence}{tool.end_sequence === null ? ' · still open' : `–${tool.end_sequence}`} · {tool.ok === null ? 'outcome unavailable' : tool.ok ? 'completed' : 'failed'} · duration {tool.duration_seconds ?? 'unavailable'} seconds</p>
    {tool.artifact_ref ? <p className="unavailable">Raw tool artifact is unavailable in the execution inspector.</p> : null}
  </article>;
}

function ResponseSummary({ response }: { response: AssistantResponse }) {
  return <section>
    <h4>Assistant response</h4>
    <p>Stop reason {response.stop_reason ?? 'unavailable'} · TTFT {response.ttft_seconds ?? 'unavailable'} seconds · duration {response.duration_seconds ?? 'unavailable'} seconds · tokens {response.input_tokens ?? '—'} in / {response.output_tokens ?? '—'} out</p>
    {response.artifact_ref ? <p className="unavailable">Raw assistant artifact is unavailable in the execution inspector.</p> : null}
  </section>;
}
