import { useMemo, useState } from 'react';
import type { BusinessProblem, RunSummary } from '../../api/types';

interface RunExplorerProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  problems?: BusinessProblem[];
  focusedProblemId?: string | null;
  onSelectRun: (analysisId: string) => void;
  onFocusProblem?: (problemId: string) => void;
}

export function RunExplorer({ runs, selectedRunId, problems = [], focusedProblemId = null, onSelectRun, onFocusProblem = () => undefined }: RunExplorerProps) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [sourceKind, setSourceKind] = useState('all');
  const sourceKinds = useMemo(() => [...new Set(runs.map((run) => run.source_kind))].sort(), [runs]);
  const visibleRuns = useMemo(() => runs.filter((run) =>
    (status === 'all' || run.status === status) &&
    (sourceKind === 'all' || run.source_kind === sourceKind) &&
    `${run.analysis_id} ${run.source_kind}`.toLowerCase().includes(query.toLowerCase()),
  ), [query, runs, sourceKind, status]);
  const statusGroups = ['completed', 'partial', 'corrupt'] as const;

  return <nav aria-label="Runs">
    <div className="rail-heading"><span>Runs</span><span>{visibleRuns.length}</span></div>
    <label className="visually-hidden" htmlFor="run-filter">Filter runs</label>
    <input id="run-filter" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter runs" />
    <label className="visually-hidden" htmlFor="run-status">Run status</label>
    <select id="run-status" value={status} onChange={(event) => setStatus(event.target.value)}>
      <option value="all">All statuses</option>
      <option value="completed">Completed</option>
      <option value="partial">Partial</option>
      <option value="corrupt">Corrupt</option>
    </select>
    <label className="visually-hidden" htmlFor="run-source-kind">Source kind</label>
    <select id="run-source-kind" value={sourceKind} onChange={(event) => setSourceKind(event.target.value)}>
      <option value="all">All sources</option>
      {sourceKinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
    </select>
    <div className="run-list">
      {statusGroups.map((group) => {
        const groupRuns = visibleRuns.filter((run) => run.status === group);
        if (groupRuns.length === 0) return null;
        const headingId = `run-group-${group}`;
        return <section key={group} className="run-group" aria-labelledby={headingId}>
          <h2 id={headingId}>{group[0].toUpperCase() + group.slice(1)} runs</h2>
          {groupRuns.map((run) => <button key={run.analysis_id} type="button"
            className={run.analysis_id === selectedRunId ? 'run-item selected' : 'run-item'}
            aria-pressed={run.analysis_id === selectedRunId} onClick={() => onSelectRun(run.analysis_id)}>
            <span>{run.analysis_id}</span><small>{run.status} · {run.source_kind} · {run.turn_count} turns</small>
          </button>)}
        </section>;
      })}
    </div>
    {selectedRunId && problems.length > 0 ? <section className="problem-index" aria-labelledby="problem-index-heading">
      <h2 id="problem-index-heading">Turn index</h2>
      {problems.map((problem, index) => {
        const nodeCount = problem.node_count ?? problem.nodes.length;
        return <button key={problem.id} type="button"
        className={problem.id === focusedProblemId ? 'problem-index-item selected' : 'problem-index-item'}
        aria-label={`${problem.title} · ${nodeCount} ${nodeCount === 1 ? 'decision' : 'decisions'}`}
        aria-pressed={problem.id === focusedProblemId}
        onClick={() => onFocusProblem(problem.id)}>
        <span>Turn {index + 1}</span><small>{nodeCount} {nodeCount === 1 ? 'decision' : 'decisions'}</small>
      </button>;
      })}
    </section> : null}
  </nav>;
}
