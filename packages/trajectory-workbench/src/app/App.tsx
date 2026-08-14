import { useEffect, useReducer, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type { BusinessProblem, RunSummary } from '../api/types';
import { Inspector } from '../components/layout/Inspector';
import { OverviewTimeline } from '../components/layout/OverviewTimeline';
import { RunExplorer } from '../components/layout/RunExplorer';
import { RunHeader } from '../components/layout/RunHeader';
import { WorkbenchShell } from '../components/layout/WorkbenchShell';
import { initialWorkbenchState, workbenchReducer } from '../state/workbench';
import { BusinessView } from '../views/BusinessView';

const api = new TrajectoryApiClient();

/** Data ownership begins here; the Task 2 shell supplies the visual regions. */
export function App({ client = api }: { client?: Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> }) {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [problems, setProblems] = useState<BusinessProblem[]>([]);

  useEffect(() => {
    const selectedNode = new URLSearchParams(window.location.search).get('node');
    if (selectedNode) dispatch({ type: 'node/selected', nodeId: selectedNode });
  }, []);

  useEffect(() => {
    if (!state.selectedNodeId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('node', state.selectedNodeId);
    window.history.replaceState(null, '', url);
  }, [state.selectedNodeId]);

  useEffect(() => {
    const controller = new AbortController();
    void client.listRuns(controller.signal).then(({ items }) => {
      setRuns(items);
      dispatch({ type: 'run/selected', runId: items[0]?.analysis_id ?? null });
    }).catch(() => undefined);
    return () => controller.abort();
  }, [client]);

  useEffect(() => {
    if (!state.selectedRunId) return;
    const controller = new AbortController();
    void client.getBusinessPage(state.selectedRunId, undefined, controller.signal).then((page) => setProblems(page.items)).catch(() => setProblems([]));
    return () => controller.abort();
  }, [client, state.selectedRunId]);

  const selectedProblem = problems.find((problem) => problem.turn_id === state.selectedNodeId) ?? null;
  const selectedRun = runs.find((run) => run.analysis_id === state.selectedRunId) ?? null;
  const selectTurn = (turnId: string) => dispatch({ type: 'node/selected', nodeId: turnId });

  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`}>
    {state.activeView === 'business' ? <BusinessView problems={problems} state={state} dispatch={dispatch} /> : <div className="view-placeholder"><h1>{state.activeView} trajectory</h1><p>This view is introduced in a subsequent workbench task.</p></div>}
  </section>;

  return <div className="workbench-bootstrap" aria-label="Trajectory workbench" data-view={state.activeView}>
    <WorkbenchShell
      header={<RunHeader run={selectedRun} activeView={state.activeView} onViewSelect={(view) => dispatch({ type: 'view/selected', view })} />}
      explorer={<RunExplorer runs={runs} selectedRunId={state.selectedRunId} onSelectRun={(runId) => dispatch({ type: 'run/selected', runId })} />}
      timeline={<OverviewTimeline problems={problems} selectedTurnId={state.selectedNodeId} onSelectTurn={selectTurn} onFocusRange={(range) => dispatch({ type: 'timeline/focused', range })} />}
      content={content}
      inspector={<Inspector node={selectedProblem} />}
      focusedTurnId={state.selectedNodeId}
    />
  </div>;
}
