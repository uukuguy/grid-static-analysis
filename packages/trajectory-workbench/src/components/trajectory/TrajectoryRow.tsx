import type { BusinessNode, NodeSource } from '../../api/types';
import { SourceBadge } from '../common/SourceBadge';

export interface BusinessTrajectoryRow extends BusinessNode {
  problemId: string;
  problemTitle: string;
}

const sourceNames: Record<NodeSource, string> = {
  observed: 'Observed', derived: 'Derived', 'agent-declared': 'Agent-declared',
};

export function TrajectoryRow({ item, selected, onSelect }: { item: BusinessTrajectoryRow; selected: boolean; onSelect: () => void }) {
  return <article className={selected ? 'trajectory-row selected' : 'trajectory-row'}>
    <button type="button" className="trajectory-row-button" onClick={onSelect} aria-pressed={selected}>
      <span className="trajectory-row-meta"><SourceBadge source={item.source} /><span>#{item.source_sequence}</span><span>{item.status}</span></span>
      <strong>{item.title}</strong>
      {item.detail && <span className="trajectory-row-detail">{item.detail}</span>}
      <span className="trajectory-row-foot">{item.kind} · {sourceNames[item.source]} · {item.refs.length} refs</span>
    </button>
  </article>;
}
