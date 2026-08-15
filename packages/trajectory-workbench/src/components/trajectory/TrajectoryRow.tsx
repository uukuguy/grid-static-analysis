import { useState } from 'react';
import type { BusinessNode } from '../../api/types';

export interface BusinessTrajectoryRow extends BusinessNode {
  problemId: string;
  problemTitle: string;
}

export function TrajectoryRow({ item, selected, onSelect }: { item: BusinessTrajectoryRow; selected: boolean; onSelect: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const detailId = `causal-row-detail-${item.id}`;
  const contextLabel = item.contextRevision === null || item.contextRevision === undefined ? 'Context unavailable' : `context r${item.contextRevision}`;
  return <article className={selected ? 'trajectory-row selected' : 'trajectory-row'}>
    <button
      type="button"
      className="causal-row"
      data-testid={`causal-node-${item.id}`}
      data-causal-kind={item.kind}
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
    >
      <span className="causal-row-meta"><span>#{item.source_sequence}</span> · {item.kind} · {item.status}</span>
      <strong>{item.title}</strong>
      <span className="causal-row-facts">{item.source} · {contextLabel} · {item.refs.length} refs</span>
    </button>
    {(item.detail || item.unavailable_reason || item.refs.length > 0) && <>
      <button
        type="button"
        className="causal-row-disclosure"
        aria-expanded={expanded}
        aria-controls={detailId}
        aria-label={`Details for #${item.source_sequence}`}
        onClick={() => setExpanded((value) => !value)}
      >
        Details
      </button>
      {expanded && <div id={detailId} className="causal-row-detail">
        {item.detail ? <p>{item.detail}</p> : null}
        {item.unavailable_reason ? <p className="unavailable">{item.unavailable_reason}</p> : null}
        {item.refs.length > 0 ? <ul aria-label={`References for ${item.title}`}>
          {item.refs.map((ref) => <li key={ref}>{ref}</li>)}
        </ul> : null}
      </div>}
    </>}
  </article>;
}
