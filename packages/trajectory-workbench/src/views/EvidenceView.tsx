import type { EvidenceIndex, EvidenceRecord } from '../api/types';
import { SourceBadge } from '../components/common/SourceBadge';

interface EvidenceViewProps { index: EvidenceIndex | null; selectedRef: string | null; onSelectRef: (ref: string) => void; artifactUrl: (ref: string) => string; }

function EvidenceRow({ record, selectedRef, onSelectRef, artifactUrl }: { record: EvidenceRecord; selectedRef: string | null; onSelectRef: (ref: string) => void; artifactUrl: (ref: string) => string }) {
  const selected = selectedRef === record.reference;
  return <div role="row" aria-selected={selected} className={selected ? 'evidence-row selected' : 'evidence-row'}>
    <span role="gridcell"><button type="button" onClick={() => onSelectRef(record.reference)} aria-label={`${record.kind} · ${record.reference} · ${record.verification_status}`}><strong>{record.kind}</strong><span>{record.reference}</span></button><small>{record.relative_path}</small></span>
    <span role="gridcell"><SourceBadge source={record.source} /><small>{record.verification_status}{record.unavailable_reason ? ` · ${record.unavailable_reason}` : ''}</small></span>
    <span role="gridcell">{record.producing_sequence ?? 'Unavailable'} · {record.consuming_sequences.join(', ') || 'no consumers'}</span>
    <span role="gridcell"><a href={artifactUrl(record.reference)} download>{record.reference}</a></span>
  </div>;
}

export function EvidenceView({ index, selectedRef, onSelectRef, artifactUrl }: EvidenceViewProps) {
  const records = index ? Object.values(index.records) : [];
  return <section className="evidence-view" aria-label="Evidence view"><header><h1>Evidence artifacts</h1><p>Immutable artifact projection returned by the trajectory API.</p></header>
    <div role="treegrid" aria-label="Evidence artifacts" className="evidence-grid"><div role="row" className="evidence-head"><span role="columnheader">Artifact / type</span><span role="columnheader">Source / verification</span><span role="columnheader">Producer / consumers</span><span role="columnheader">Download</span></div>
      {records.map((record) => <EvidenceRow key={record.reference} record={record} selectedRef={selectedRef} onSelectRef={onSelectRef} artifactUrl={artifactUrl} />)}
    </div>
    {records.length === 0 ? <p className="unavailable">No evidence artifacts are available for this run.</p> : null}
  </section>;
}
