import type { KeyboardEvent } from 'react';
import { useState } from 'react';
import type { BusinessNode, BusinessProblem } from '../../api/types';
import { SourceBadge } from '../common/SourceBadge';

const tabs = ['Identity', 'Input', 'Output', 'Timing', 'Context Delta', 'References', 'Artifacts'] as const;
type InspectorTab = typeof tabs[number];

export interface InspectorEntity { problem: BusinessProblem; node: BusinessNode | null; }

export function Inspector({ entity, artifactUrl }: { entity: InspectorEntity | null; artifactUrl: (ref: string) => string }) {
  const [active, setActive] = useState<InspectorTab>('Identity');
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    setActive(tabs[next]);
    document.getElementById(`inspector-tab-${tabs[next]}`)?.focus();
  };
  return <div className="inspector-content">
    <div role="tablist" aria-label="Inspector details" className="inspector-tabs">
      {tabs.map((tab, index) => <button key={tab} id={`inspector-tab-${tab}`} type="button" role="tab" aria-selected={active === tab} tabIndex={active === tab ? 0 : -1} onClick={() => setActive(tab)} onKeyDown={(event) => onKeyDown(event, index)}>{tab}</button>)}
    </div>
    <section role="tabpanel" aria-label={active} className="inspector-panel">
      {!entity ? <p>Select a turn or node to inspect its recorded details.</p> : <InspectorPanel entity={entity} active={active} artifactUrl={artifactUrl} />}
    </section>
  </div>;
}

function InspectorPanel({ entity, active, artifactUrl }: { entity: InspectorEntity; active: InspectorTab; artifactUrl: (ref: string) => string }) {
  const { problem, node } = entity;
  const selected = node ?? problem;
  const refs = node?.refs ?? problem.nodes.flatMap((item) => item.refs);
  if (active === 'Identity') return <dl>
    <dt>Node</dt><dd>{selected.id}</dd><dt>Turn</dt><dd>{problem.turn_id}</dd>{node ? <><dt>Problem</dt><dd>{problem.title}</dd><dt>Kind</dt><dd>{node.kind}</dd><dt>Title</dt><dd>{node.title}</dd>{node.detail ? <><dt>Detail</dt><dd>{node.detail}</dd></> : null}</> : null}<dt>Source</dt><dd><SourceBadge source={selected.source} /></dd><dt>Status</dt><dd>{selected.status}</dd><dt>Sequence</dt><dd>{node?.source_sequence ?? problem.source_sequence}</dd>
  </dl>;
  if (active === 'References' || active === 'Artifacts') return refs.length
    ? <ul>{refs.map((ref) => <li key={ref}><a href={artifactUrl(ref)} download>{ref}</a></li>)}</ul>
    : <p>No artifact references are recorded for this {node ? 'node' : 'problem'}.</p>;
  return <pre>{JSON.stringify({ node: selected.id, tab: active, source_sequences: selected.source_sequences }, null, 2)}</pre>;
}
