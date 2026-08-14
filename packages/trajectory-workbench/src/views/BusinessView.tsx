import type { BusinessProblem, LifecycleStatus, NodeSource } from '../api/types';
import { TrajectoryRow, type BusinessTrajectoryRow } from '../components/trajectory/TrajectoryRow';
import { VirtualTrajectory, type PrependAnchor } from '../components/trajectory/VirtualTrajectory';
import type { WorkbenchAction, WorkbenchState } from '../state/workbench';

interface BusinessViewProps {
  problems: BusinessProblem[];
  state: WorkbenchState;
  dispatch: React.Dispatch<WorkbenchAction>;
  hasOlder?: boolean;
  onRequestOlder?: (anchor: PrependAnchor) => void;
}

function filteredRows(problems: BusinessProblem[], state: WorkbenchState): BusinessTrajectoryRow[] {
  const query = state.search.trim().toLowerCase();
  return problems.flatMap((problem) => state.foldedNodeIds.includes(problem.id) ? [] : problem.nodes.map((node) => ({ ...node, problemId: problem.id, problemTitle: problem.title })))
    .filter((node) => !query || [node.title, node.detail, node.kind, node.status, node.source].some((value) => value?.toLowerCase().includes(query)))
    .filter((node) => state.sourceFilter === 'all' || node.source === state.sourceFilter)
    .filter((node) => state.statusFilter === 'all' || node.status === state.statusFilter)
    .filter((node) => !state.timelineRange || (node.source_sequence >= state.timelineRange.startSequence && node.source_sequence <= state.timelineRange.endSequence));
}

export function BusinessView({ problems, state, dispatch, hasOlder = false, onRequestOlder = () => undefined }: BusinessViewProps) {
  const rows = filteredRows(problems, state);
  const sources: NodeSource[] = ['observed', 'derived', 'agent-declared'];
  const statuses: LifecycleStatus[] = ['running', 'completed', 'failed', 'interrupted', 'unavailable'];
  return <section className="business-view" aria-label="Business trajectory view">
    <header className="business-view-header"><div><h1>Business trajectory</h1><p>Chronological problem-solving evidence</p></div>
      <div className="business-controls"><label>Search business trajectory<input aria-label="Search business trajectory" value={state.search} onChange={(event) => dispatch({ type: 'search/changed', search: event.target.value })} placeholder="Search decisions, tools, claims" /></label>
      <label>Source filter<select aria-label="Source filter" value={state.sourceFilter} onChange={(event) => dispatch({ type: 'sourceFilter/changed', source: event.target.value as NodeSource | 'all' })}><option value="all">All sources</option>{sources.map((source) => <option value={source} key={source}>{source}</option>)}</select></label>
      <label>Status filter<select aria-label="Status filter" value={state.statusFilter} onChange={(event) => dispatch({ type: 'statusFilter/changed', status: event.target.value as LifecycleStatus | 'all' })}><option value="all">All states</option>{statuses.map((status) => <option value={status} key={status}>{status}</option>)}</select></label></div>
    </header>
    <section className="business-problems" aria-label="Business problems">
      {problems.map((problem) => <div className="business-problem" key={problem.id}>
        <button type="button" className="problem-fold" aria-expanded={!state.foldedNodeIds.includes(problem.id)} onClick={() => dispatch({ type: 'node/foldToggled', nodeId: problem.id })} aria-label={`${state.foldedNodeIds.includes(problem.id) ? 'Expand' : 'Fold'} ${problem.title}`}>
          <span>{state.foldedNodeIds.includes(problem.id) ? '▸' : '▾'}</span><strong>{problem.title}</strong><small>{problem.status} · {problem.nodes.length} events</small>
        </button>
      </div>)}
    </section>
    <div className="business-filter-summary" aria-label="Business trajectory filters">{sources.length + statuses.length} available filters · {rows.length} matching events</div>
    <VirtualTrajectory items={rows} label="Business trajectory" hasOlder={hasOlder} onRequestOlder={onRequestOlder} renderRow={(item) => <TrajectoryRow item={item} selected={state.selectedNodeId === item.id} onSelect={() => dispatch({ type: 'node/selected', nodeId: item.id })} />} />
  </section>;
}
