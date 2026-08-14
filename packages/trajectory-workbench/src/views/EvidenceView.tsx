import type { EvidenceIndex, EvidenceNode } from '../api/types';
import { SourceBadge } from '../components/common/SourceBadge';

interface EvidenceViewProps { index: EvidenceIndex; selectedRef: string | null; onSelectRef: (ref: string) => void; artifactUrl: (ref: string) => string; }

function accessibleLabel(node: EvidenceNode) { return `${node.type[0].toUpperCase()}${node.type.slice(1)} · ${node.label} · ${node.integrity}`; }

export function EvidenceView({ index, selectedRef, onSelectRef, artifactUrl }: EvidenceViewProps) {
  const move = (event: React.KeyboardEvent<HTMLButtonElement>, indexAt: number) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? index.nodes.length - 1 : (indexAt + (event.key === 'ArrowDown' ? 1 : -1) + index.nodes.length) % index.nodes.length;
    document.getElementById(`evidence-node-${index.nodes[next]?.ref}`)?.focus();
  };
  const relationSummary = (ref: string) => index.relations.filter((relation) => relation.from_ref === ref || relation.to_ref === ref).map((relation) => relation.from_ref === ref ? `${relation.relation} → ${relation.to_ref}` : `${relation.from_ref} → ${relation.relation}`).join('; ') || 'No recorded relationships';
  return <section className="evidence-view" aria-label="Evidence view"><header><h1>Evidence relationships</h1><p>Declared and observed references only; answer text does not create relationships.</p></header>
    <div role="treegrid" aria-label="Evidence relationships" className="evidence-grid"><div role="row" className="evidence-head"><span role="columnheader">Relation / type</span><span role="columnheader">Source / integrity</span><span role="columnheader">Sequence / consumers</span><span role="columnheader">Artifact</span></div>
      {index.nodes.map((node, position) => <div role="row" key={node.ref} aria-selected={selectedRef === node.ref} className={selectedRef === node.ref ? 'evidence-row selected' : 'evidence-row'}>
        <span role="gridcell"><button id={`evidence-node-${node.ref}`} type="button" onClick={() => onSelectRef(node.ref)} onKeyDown={(event) => move(event, position)} aria-label={accessibleLabel(node)}><strong>{node.type}</strong><span>{node.label}</span></button><small>{relationSummary(node.ref)}</small></span>
        <span role="gridcell"><SourceBadge source={node.source} /><small>{node.integrity}{node.unavailable_reason ? ` · ${node.unavailable_reason}` : ''}</small></span>
        <span role="gridcell">{node.producing_sequence ?? 'Unavailable'} · {node.consumers}</span>
        <span role="gridcell">{node.artifact_ref ? <a href={artifactUrl(node.artifact_ref)} download>{node.artifact_ref}</a> : 'Unavailable'}</span>
      </div>)}
    </div>
    {index.nodes.length === 0 ? <p className="unavailable">No evidence relationships are available for this run.</p> : null}
  </section>;
}
