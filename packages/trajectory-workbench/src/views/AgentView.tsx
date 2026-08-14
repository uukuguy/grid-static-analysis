import { useState } from 'react';
import type { AgentRetry, AgentTurn, ModelRequest, ProjectionNode, ToolCall } from '../api/types';
import { SourceBadge } from '../components/common/SourceBadge';

interface AgentViewProps {
  trajectory: AgentTurn[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  artifactUrl: (ref: string) => string;
}

function ArtifactLink({ reference, artifactUrl }: { reference: string | null; artifactUrl: (ref: string) => string }) {
  return reference ? <a href={artifactUrl(reference)} download>{reference}</a> : <span className="unavailable">Artifact unavailable</span>;
}

function TreeItem({ node, level, children, onSelectNode, selected, label }: { node: ProjectionNode; level: number; children?: React.ReactNode; onSelectNode: (nodeId: string) => void; selected: boolean; label: React.ReactNode }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = Boolean(children);
  return <li role="treeitem" aria-level={level} aria-expanded={hasChildren ? expanded : undefined} aria-selected={selected} className="agent-tree-item">
    <div className="agent-tree-row">
      {hasChildren ? <button type="button" className="tree-toggle" aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.id}`} onClick={() => setExpanded((value) => !value)}>{expanded ? '▾' : '▸'}</button> : <span className="tree-spacer" aria-hidden="true" />}
      <button type="button" className="agent-node" onClick={() => onSelectNode(node.id)}>{label}</button>
    </div>
    {hasChildren && expanded ? <ul role="group">{children}</ul> : null}
  </li>;
}

function RetryItem({ retry, onSelectNode, selected }: { retry: AgentRetry; onSelectNode: (id: string) => void; selected: boolean }) {
  return <TreeItem node={retry} level={4} onSelectNode={onSelectNode} selected={selected} label={<><strong>Retry {retry.attempt} of {retry.max_attempts}</strong><span>{retry.delay_seconds === null ? 'No recorded delay' : `Delay ${retry.delay_seconds} s`}{retry.message ? ` · ${retry.message}` : ''}</span></>} />;
}

function ToolItem({ tool, onSelectNode, selected, artifactUrl }: { tool: ToolCall; onSelectNode: (id: string) => void; selected: boolean; artifactUrl: (ref: string) => string }) {
  return <TreeItem node={tool} level={4} onSelectNode={onSelectNode} selected={selected} label={<><strong>{tool.capability} · {tool.status}</strong><span>Sequence {tool.start_sequence}{tool.end_sequence === null ? ' · still open' : `–${tool.end_sequence}`} · {tool.duration_seconds === null ? 'duration unavailable' : `${tool.duration_seconds} s`} · {tool.ok === null ? 'outcome unavailable' : tool.ok ? 'completed' : 'failed'} · <ArtifactLink reference={tool.artifact_ref} artifactUrl={artifactUrl} /></span></>} />;
}

function RequestItem({ request, onSelectNode, selectedNodeId, artifactUrl }: { request: ModelRequest; onSelectNode: (id: string) => void; selectedNodeId: string | null; artifactUrl: (ref: string) => string }) {
  const response = request.response;
  return <TreeItem node={request} level={3} onSelectNode={onSelectNode} selected={selectedNodeId === request.id} label={<><strong>Request {request.request_id}</strong><span>Sequence {request.source_sequences.join(', ')} · request input <ArtifactLink reference={request.artifact_ref} artifactUrl={artifactUrl} /></span></>}>
    {request.retries.map((retry) => <RetryItem key={retry.id} retry={retry} onSelectNode={onSelectNode} selected={selectedNodeId === retry.id} />)}
    {request.tools.map((tool) => <ToolItem key={tool.id} tool={tool} onSelectNode={onSelectNode} selected={selectedNodeId === tool.id} artifactUrl={artifactUrl} />)}
    {response ? <TreeItem node={response} level={4} onSelectNode={onSelectNode} selected={selectedNodeId === response.id} label={<><strong>Assistant response · {response.status}</strong><span>TTFT {response.ttft_seconds === null ? 'unavailable' : `${response.ttft_seconds} s`} · duration {response.duration_seconds === null ? 'unavailable' : `${response.duration_seconds} s`} · {response.input_tokens ?? '—'} input / {response.output_tokens ?? '—'} output tokens · <ArtifactLink reference={response.artifact_ref} artifactUrl={artifactUrl} /></span></>} /> : null}
  </TreeItem>;
}

export function AgentView({ trajectory, selectedNodeId, onSelectNode, artifactUrl }: AgentViewProps) {
  return <section className="agent-view" aria-label="Agent trajectory view"><header><h1>Agent trace</h1><p>Recorded requests, retries, public responses, and typed tool lifecycles.</p></header>
    {trajectory.length === 0 ? <p className="unavailable">No agent trace is available for this run.</p> : <ul role="tree" aria-label="Agent trace">
      {trajectory.map((turn) => <TreeItem key={turn.id} node={turn} level={1} onSelectNode={onSelectNode} selected={selectedNodeId === turn.id} label={<><strong>Turn {turn.ordinal ?? '—'} · {turn.turn_id}</strong><span>Sequence {turn.source_sequence} · <SourceBadge source={turn.source} /></span></>}>
        {turn.steps.map((step) => <TreeItem key={step.id} node={step} level={2} onSelectNode={onSelectNode} selected={selectedNodeId === step.id} label={<><strong>Step {step.step_id}</strong><span>{step.request ? 'Recorded model request' : step.unavailable_reason ?? 'No model request'}</span></>}>
          {step.request ? <RequestItem request={step.request} onSelectNode={onSelectNode} selectedNodeId={selectedNodeId} artifactUrl={artifactUrl} /> : null}
        </TreeItem>)}
      </TreeItem>)}
    </ul>}
  </section>;
}
