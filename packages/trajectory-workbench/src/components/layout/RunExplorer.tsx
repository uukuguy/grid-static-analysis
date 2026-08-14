import { useMemo, useState } from 'react';
import type { RunSummary } from '../../api/types';

interface RunExplorerProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (analysisId: string) => void;
}

export function RunExplorer({ runs, selectedRunId, onSelectRun }: RunExplorerProps) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const visibleRuns = useMemo(() => runs.filter((run) =>
    (status === 'all' || run.status === status) &&
    `${run.analysis_id} ${run.source_kind}`.toLowerCase().includes(query.toLowerCase()),
  ), [query, runs, status]);

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
    <div className="run-list">
      {visibleRuns.map((run) => <button key={run.analysis_id} type="button"
        className={run.analysis_id === selectedRunId ? 'run-item selected' : 'run-item'}
        aria-pressed={run.analysis_id === selectedRunId} onClick={() => onSelectRun(run.analysis_id)}>
        <span>{run.analysis_id}</span><small>{run.status} · {run.source_kind} · {run.turn_count} turns</small>
      </button>)}
    </div>
  </nav>;
}
