import { useEffect, useMemo, useRef, useState } from 'react';
import type { AgentTurn, ProjectionNode } from '../api/types';
import { SourceBadge } from '../components/common/SourceBadge';

interface AgentViewProps { trajectory: AgentTurn[]; selectedNodeId: string | null; onSelectNode: (nodeId: string) => void; artifactUrl: (ref: string) => string; }

interface TreeEntry { node: ProjectionNode; parentId: string | null; level: number; label: React.ReactNode; }

function ArtifactLink({ reference, artifactUrl }: { reference: string | null; artifactUrl: (ref: string) => string }) {
  return reference ? <a href={artifactUrl(reference)} download>{reference}</a> : <span className="unavailable">Artifact unavailable</span>;
}

function entriesFor(trajectory: AgentTurn[], artifactUrl: (ref: string) => string): TreeEntry[] {
  const entries: TreeEntry[] = [];
  for (const turn of trajectory) {
    entries.push({ node: turn, parentId: null, level: 1, label: <><strong>Turn {turn.ordinal ?? '—'} · {turn.turn_id}</strong><span>Sequence {turn.source_sequences.join(', ')} · <SourceBadge source={turn.source} /></span></> });
    for (const step of turn.steps) {
      entries.push({ node: step, parentId: turn.id, level: 2, label: <><strong>Step {step.step_id}</strong><span>{step.request ? 'Recorded model request' : step.unavailable_reason ?? 'No model request'}</span></> });
      if (!step.request) continue;
      const request = step.request;
      entries.push({ node: request, parentId: step.id, level: 3, label: <><strong>Request {request.request_id}</strong><span>Sequence {request.source_sequences.join(', ')} · request input <ArtifactLink reference={request.artifact_ref} artifactUrl={artifactUrl} /></span></> });
      for (const retry of request.retries) entries.push({ node: retry, parentId: request.id, level: 4, label: <><strong>Retry {retry.attempt} of {retry.max_attempts}</strong><span>{retry.delay_seconds === null ? 'No recorded delay' : `Delay ${retry.delay_seconds} s`}{retry.message ? ` · ${retry.message}` : ''}</span></> });
      for (const tool of request.tools) entries.push({ node: tool, parentId: request.id, level: 4, label: <><strong>{tool.capability} · {tool.status}</strong><span>Sequence {tool.start_sequence}{tool.end_sequence === null ? ' · still open' : `–${tool.end_sequence}`} · {tool.duration_seconds === null ? 'duration unavailable' : `${tool.duration_seconds} s`} · {tool.ok === null ? 'outcome unavailable' : tool.ok ? 'completed' : 'failed'} · <ArtifactLink reference={tool.artifact_ref} artifactUrl={artifactUrl} /></span></> });
      if (request.response) {
        const response = request.response;
        entries.push({ node: response, parentId: request.id, level: 4, label: <><strong>Assistant response · {response.status}</strong><span>TTFT {response.ttft_seconds === null ? 'unavailable' : `${response.ttft_seconds} s`} · duration {response.duration_seconds === null ? 'unavailable' : `${response.duration_seconds} s`} · {response.input_tokens ?? '—'} input / {response.output_tokens ?? '—'} output tokens · <ArtifactLink reference={response.artifact_ref} artifactUrl={artifactUrl} /></span></> });
      }
    }
  }
  return entries;
}

export function AgentView({ trajectory, selectedNodeId, onSelectNode, artifactUrl }: AgentViewProps) {
  const entries = useMemo(() => entriesFor(trajectory, artifactUrl), [trajectory, artifactUrl]);
  const children = useMemo(() => new Map(entries.map((entry) => [entry.node.id, entries.filter((candidate) => candidate.parentId === entry.node.id)])), [entries]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(entries.filter((entry) => children.get(entry.node.id)?.length).map((entry) => entry.node.id)));
  const [activeId, setActiveId] = useState<string | null>(() => entries[0]?.node.id ?? null);
  const itemRefs = useRef(new Map<string, HTMLLIElement>());
  useEffect(() => {
    setActiveId((current) => current && entries.some((entry) => entry.node.id === current) ? current : entries[0]?.node.id ?? null);
  }, [entries]);
  const visible = entries.filter((entry) => {
    for (let parentId = entry.parentId; parentId; parentId = entries.find((candidate) => candidate.node.id === parentId)?.parentId ?? null) if (!expanded.has(parentId)) return false;
    return true;
  });
  const focus = (id: string) => { itemRefs.current.get(id)?.focus(); setActiveId(id); };
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const keyDown = (event: React.KeyboardEvent<HTMLLIElement>, entry: TreeEntry) => {
    const position = visible.findIndex((item) => item.node.id === entry.node.id);
    const childEntries = children.get(entry.node.id) ?? [];
    if (event.key === 'ArrowDown' && position < visible.length - 1) { event.preventDefault(); focus(visible[position + 1].node.id); }
    else if (event.key === 'ArrowUp' && position > 0) { event.preventDefault(); focus(visible[position - 1].node.id); }
    else if (event.key === 'Home' && visible[0]) { event.preventDefault(); focus(visible[0].node.id); }
    else if (event.key === 'End' && visible.at(-1)) { event.preventDefault(); focus(visible.at(-1)!.node.id); }
    else if (event.key === 'ArrowRight' && childEntries.length) { event.preventDefault(); if (!expanded.has(entry.node.id)) toggle(entry.node.id); else focus(childEntries[0].node.id); }
    else if (event.key === 'ArrowLeft') { event.preventDefault(); if (childEntries.length && expanded.has(entry.node.id)) toggle(entry.node.id); else if (entry.parentId) focus(entry.parentId); }
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelectNode(entry.node.id); }
  };
  return <section className="agent-view" aria-label="Agent trajectory view"><header><h1>Agent trace</h1><p>Recorded requests, retries, public responses, and typed tool lifecycles.</p></header>
    {entries.length === 0 ? <p className="unavailable">No agent trace is available for this run.</p> : <ul role="tree" aria-label="Agent trace">
      {visible.map((entry) => { const hasChildren = (children.get(entry.node.id)?.length ?? 0) > 0; const isExpanded = expanded.has(entry.node.id); return <li key={entry.node.id} ref={(element) => { if (element) itemRefs.current.set(entry.node.id, element); else itemRefs.current.delete(entry.node.id); }} role="treeitem" aria-level={entry.level} aria-expanded={hasChildren ? isExpanded : undefined} aria-selected={selectedNodeId === entry.node.id} tabIndex={activeId === entry.node.id ? 0 : -1} className="agent-tree-item" onFocus={() => setActiveId(entry.node.id)} onClick={() => onSelectNode(entry.node.id)} onKeyDown={(event) => keyDown(event, entry)}>
        <div className="agent-tree-row">{hasChildren ? <button type="button" className="tree-toggle" tabIndex={-1} aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${entry.node.id}`} onClick={(event) => { event.stopPropagation(); toggle(entry.node.id); }}>{isExpanded ? '▾' : '▸'}</button> : <span className="tree-spacer" aria-hidden="true" />}<div className="agent-node">{entry.label}</div></div>
      </li>; })}
    </ul>}
  </section>;
}
