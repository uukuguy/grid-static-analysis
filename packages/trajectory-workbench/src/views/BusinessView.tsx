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
  olderState?: 'idle' | 'loading' | 'failed';
  olderError?: string | null;
  onRetryOlder?: () => void;
}

type BusinessViewItem = ({ type: 'node' } & BusinessTrajectoryRow) | { id: string; source_sequence: number; type: 'problem'; problem: BusinessProblem };

function filteredRows(problems: BusinessProblem[], state: WorkbenchState): BusinessViewItem[] {
  const query = state.search.trim().toLowerCase();
  return problems.flatMap((problem) => [
    { id: `problem:${problem.id}`, source_sequence: problem.source_sequence, type: 'problem' as const, problem },
    ...(state.foldedNodeIds.includes(problem.id) ? [] : problem.nodes
      .filter((node) => !query || [node.title, node.detail, node.kind, node.status, node.source].some((value) => value?.toLowerCase().includes(query)))
      .filter((node) => state.sourceFilter === 'all' || node.source === state.sourceFilter)
      .filter((node) => state.statusFilter === 'all' || node.status === state.statusFilter)
      .filter((node) => !state.timelineRange || (node.source_sequence >= state.timelineRange.startSequence && node.source_sequence <= state.timelineRange.endSequence))
      .map((node) => ({ ...node, type: 'node' as const, problemId: problem.id, problemTitle: problem.title }))),
  ]);
}

export function BusinessView({
  problems,
  state,
  dispatch,
  hasOlder = false,
  onRequestOlder = () => undefined,
  olderState = 'idle',
  olderError = null,
  onRetryOlder = () => undefined,
}: BusinessViewProps) {
  const rows = filteredRows(problems, state);
  const sources: NodeSource[] = ['observed', 'derived', 'agent-declared'];
  const statuses: LifecycleStatus[] = ['running', 'completed', 'failed', 'interrupted', 'unavailable'];
  const focusedProblemRowId = state.focusedProblemId ? `problem:${state.focusedProblemId}` : null;
  const focusedProblemHeadingId = state.focusedProblemId ? problemHeadingId(state.focusedProblemId) : null;

  return <section className="business-view" aria-label="Business trajectory view">
    <header className="business-view-header"><div><h1>Business trajectory</h1><p>Chronological problem-solving evidence</p></div>
      <div className="business-controls"><label>Search business trajectory<input aria-label="Search business trajectory" value={state.search} onChange={(event) => dispatch({ type: 'search/changed', search: event.target.value })} placeholder="Search decisions, tools, claims" /></label>
      <label>Source filter<select aria-label="Source filter" value={state.sourceFilter} onChange={(event) => dispatch({ type: 'sourceFilter/changed', source: event.target.value as NodeSource | 'all' })}><option value="all">All sources</option>{sources.map((source) => <option value={source} key={source}>{source}</option>)}</select></label>
      <label>Status filter<select aria-label="Status filter" value={state.statusFilter} onChange={(event) => dispatch({ type: 'statusFilter/changed', status: event.target.value as LifecycleStatus | 'all' })}><option value="all">All states</option>{statuses.map((status) => <option value={status} key={status}>{status}</option>)}</select></label></div>
    </header>
    <div className="business-filter-summary" aria-label="Business trajectory filters">{sources.length + statuses.length} available filters · {rows.length} matching events</div>
    <VirtualTrajectory
      items={rows}
      label="Business trajectory"
      hasOlder={hasOlder}
      onRequestOlder={onRequestOlder}
      olderState={olderState}
      olderError={olderError}
      onRetryOlder={onRetryOlder}
      estimateSize={(item) => item.type === 'problem' ? 52 : 44}
      focusItemId={focusedProblemRowId}
      focusElementId={focusedProblemHeadingId}
      renderRow={(item) => item.type === 'problem'
      ? <div className="problem-group-header" data-testid={`problem-header-${item.problem.id}`}>
        <h2 id={problemHeadingId(item.problem.id)} tabIndex={-1}>{item.problem.title}</h2>
        <button type="button" className="problem-fold" aria-expanded={!state.foldedNodeIds.includes(item.problem.id)} onClick={() => dispatch({ type: 'node/foldToggled', nodeId: item.problem.id })} aria-label={`${state.foldedNodeIds.includes(item.problem.id) ? 'Expand' : 'Fold'} ${item.problem.title}`}>
          <span>{state.foldedNodeIds.includes(item.problem.id) ? '▸' : '▾'}</span><small>{item.problem.status} · {item.problem.node_count ?? item.problem.nodes.length} events</small>
        </button>
      </div>
      : <TrajectoryRow item={item} selected={state.selectedNodeId === item.id} onSelect={() => dispatch({ type: 'node/selected', nodeId: item.id })} />}
    />
  </section>;
}

function problemHeadingId(problemId: string) {
  return `business-problem-heading-${problemId}`;
}
