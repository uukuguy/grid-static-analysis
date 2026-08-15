import type { NodeSource } from '../../api/types';
import { Icon } from './Icon';

const labels = { observed: 'Observed', derived: 'Derived', 'agent-declared': 'Agent-declared' } as const;
const icons = { observed: 'eye', derived: 'function', 'agent-declared': 'spark' } as const;

export function SourceBadge({ source }: { source: NodeSource }) {
  return <span className={`source-badge source-${source}`}><Icon name={icons[source]} />{labels[source]}</span>;
}
