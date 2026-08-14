import { useEffect, useReducer, useRef, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type { BusinessProblem, ProjectionPage, RunSummary } from '../api/types';
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
  const [businessPage, setBusinessPage] = useState<Pick<ProjectionPage<BusinessProblem>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const loadingOlder = useRef(false);
  const businessPageRef = useRef<Pick<ProjectionPage<BusinessProblem>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const deepLinkNode = useRef(new URLSearchParams(window.location.search).get('node'));

  useEffect(() => {
    const selectedNode = deepLinkNode.current;
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
      if (deepLinkNode.current) dispatch({ type: 'node/selected', nodeId: deepLinkNode.current });
    }).catch(() => undefined);
    return () => controller.abort();
  }, [client]);

  useEffect(() => {
    if (!state.selectedRunId) return;
    const controller = new AbortController();
    dispatch({ type: 'page/requested', view: 'business' });
    void client.getBusinessPage(state.selectedRunId, undefined, controller.signal).then((page) => {
      setProblems(page.items);
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/loaded', view: 'business', page: pageMetadata(page) });
    }).catch(() => {
      setProblems([]);
      businessPageRef.current = { older_cursor: null, has_older: false };
      setBusinessPage({ older_cursor: null, has_older: false });
      dispatch({ type: 'page/failed', view: 'business', message: 'Unable to load business trajectory.' });
    });
    return () => controller.abort();
  }, [client, state.selectedRunId]);

  const selectedProblem = problems.find((problem) => problem.id === state.selectedNodeId || problem.turn_id === state.selectedNodeId || problem.nodes.some((node) => node.id === state.selectedNodeId)) ?? null;
  const selectedRun = runs.find((run) => run.analysis_id === state.selectedRunId) ?? null;
  const selectTurn = (turnId: string) => dispatch({ type: 'node/selected', nodeId: turnId });
  const requestOlder = () => {
    const runId = state.selectedRunId;
    const page = businessPageRef.current;
    const cursor = page.older_cursor;
    if (!runId || !page.has_older || !cursor || loadingOlder.current) return;
    loadingOlder.current = true;
    dispatch({ type: 'page/requested', view: 'business' });
    void client.getBusinessPage(runId, cursor).then((page) => {
      setProblems((current) => prependProblems(page.items, current));
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/prepended', view: 'business', page: pageMetadata(page) });
    }).catch(() => dispatch({ type: 'page/failed', view: 'business', message: 'Unable to load older business trajectory.' }))
      .finally(() => { loadingOlder.current = false; });
  };

  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`}>
    {state.activeView === 'business' ? <BusinessView problems={problems} state={state} dispatch={dispatch} hasOlder={businessPage.has_older} onRequestOlder={requestOlder} /> : <div className="view-placeholder"><h1>{state.activeView} trajectory</h1><p>This view is introduced in a subsequent workbench task.</p></div>}
  </section>;

  return <div className="workbench-bootstrap" aria-label="Trajectory workbench" data-view={state.activeView}>
    <WorkbenchShell
      header={<RunHeader run={selectedRun} activeView={state.activeView} onViewSelect={(view) => dispatch({ type: 'view/selected', view })} />}
      explorer={<RunExplorer runs={runs} selectedRunId={state.selectedRunId} onSelectRun={(runId) => dispatch({ type: 'run/selected', runId })} />}
      timeline={<OverviewTimeline problems={problems} selectedTurnId={selectedProblem?.turn_id ?? state.selectedNodeId} onSelectTurn={selectTurn} onFocusRange={(range) => dispatch({ type: 'timeline/focused', range })} />}
      content={content}
      inspector={<Inspector node={selectedProblem} />}
      focusedTurnId={selectedProblem?.turn_id ?? state.selectedNodeId}
    />
  </div>;
}

function pageMetadata(page: ProjectionPage<BusinessProblem>) {
  return {
    firstSequence: page.first_sequence,
    lastSequence: page.last_sequence,
    hasOlder: page.has_older,
    olderCursor: page.older_cursor,
  };
}

/** Older API pages always precede the loaded tail; de-duplicate retries by durable ID. */
function prependProblems(older: BusinessProblem[], current: BusinessProblem[]) {
  const seen = new Set<string>();
  return [...older, ...current].filter((problem) => !seen.has(problem.id) && (seen.add(problem.id), true));
}
