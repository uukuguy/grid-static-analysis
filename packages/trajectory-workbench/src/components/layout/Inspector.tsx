import type { KeyboardEvent } from 'react';
import { useState } from 'react';
import type { BusinessProblem } from '../../api/types';
import { SourceBadge } from '../common/SourceBadge';

const tabs = ['Identity', 'Input', 'Output', 'Timing', 'Context Delta', 'References', 'Artifacts'] as const;
type InspectorTab = typeof tabs[number];

export function Inspector({ node }: { node: BusinessProblem | null }) {
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
      {!node ? <p>Select a turn or node to inspect its recorded details.</p> : active === 'Identity' ? <dl>
        <dt>Node</dt><dd>{node.id}</dd><dt>Turn</dt><dd>{node.turn_id}</dd><dt>Source</dt><dd><SourceBadge source={node.source} /></dd><dt>Status</dt><dd>{node.status}</dd>
      </dl> : active === 'References' ? <ul>{node.nodes.flatMap((item) => item.refs).map((ref) => <li key={ref}>{ref}</li>)}</ul>
        : active === 'Artifacts' ? <p>No directly linked artifact is available in this summary.</p>
        : <pre>{JSON.stringify({ node: node.id, tab: active, source_sequences: node.source_sequences }, null, 2)}</pre>}
    </section>
  </div>;
}
