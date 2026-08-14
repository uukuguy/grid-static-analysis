import { useEffect, useReducer, useRef, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type { AgentTurn, BusinessProblem, ContextFrame, EvidenceIndex, EvidenceNode, ProjectionPage, RunSummary } from '../api/types';
import { Inspector } from '../components/layout/Inspector';
import { OverviewTimeline } from '../components/layout/OverviewTimeline';
import { RunExplorer } from '../components/layout/RunExplorer';
import { RunHeader } from '../components/layout/RunHeader';
import { WorkbenchShell } from '../components/layout/WorkbenchShell';
import { initialWorkbenchState, workbenchReducer } from '../state/workbench';
import { BusinessView } from '../views/BusinessView';
import { AgentView } from '../views/AgentView';
import { ContextView } from '../views/ContextView';
import { EvidenceView } from '../views/EvidenceView';

const api = new TrajectoryApiClient();

/** Data ownership begins here; the Task 2 shell supplies the visual regions. */
type AppClient = Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> & Partial<Pick<TrajectoryApiClient, 'getAgentPage' | 'getContextFrame' | 'artifactUrl'>>;

export function App({ client = api }: { client?: AppClient }) {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [problems, setProblems] = useState<BusinessProblem[]>([]);
  const [agentTurns, setAgentTurns] = useState<AgentTurn[]>([]);
  const [contextFrame, setContextFrame] = useState<ContextFrame | null>(null);
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

  useEffect(() => {
    if (state.activeView !== 'agent' || !state.selectedRunId || !client.getAgentPage) return;
    const controller = new AbortController();
    dispatch({ type: 'page/requested', view: 'agent' });
    void client.getAgentPage(state.selectedRunId, undefined, controller.signal).then((page) => {
      setAgentTurns(page.items);
      dispatch({ type: 'page/loaded', view: 'agent', page: pageMetadata(page) });
    }).catch(() => dispatch({ type: 'page/failed', view: 'agent', message: 'Unable to load agent trajectory.' }));
    return () => controller.abort();
  }, [client, state.activeView, state.selectedRunId]);

  const selectedProblem = problems.find((problem) => problem.id === state.selectedNodeId || problem.turn_id === state.selectedNodeId || problem.nodes.some((node) => node.id === state.selectedNodeId)) ?? null;
  const selectedRun = runs.find((run) => run.analysis_id === state.selectedRunId) ?? null;

  useEffect(() => {
    if (state.activeView !== 'context' || !state.selectedRunId || !client.getContextFrame) return;
    const sequence = selectedProblem?.source_sequence ?? selectedRun?.last_sequence;
    if (!sequence || sequence < 1) return;
    const controller = new AbortController();
    dispatch({ type: 'page/requested', view: 'context' });
    void client.getContextFrame(state.selectedRunId, sequence, controller.signal).then((frame) => {
      setContextFrame(frame);
      dispatch({ type: 'page/loaded', view: 'context', page: { firstSequence: frame.source_sequence, lastSequence: frame.source_sequence, hasOlder: false } });
    }).catch(() => { setContextFrame(null); dispatch({ type: 'page/failed', view: 'context', message: 'Unable to load context frame.' }); });
    return () => controller.abort();
  }, [client, state.activeView, state.selectedRunId, state.selectedNodeId, selectedProblem?.source_sequence, selectedRun?.last_sequence]);

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

  const artifactUrl = (ref: string) => client.artifactUrl ? client.artifactUrl(state.selectedRunId ?? '', ref) : '#';
  const evidenceIndex = evidenceFromProblems(problems);
  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`}>
    {state.activeView === 'business' ? <BusinessView problems={problems} state={state} dispatch={dispatch} hasOlder={businessPage.has_older} onRequestOlder={requestOlder} />
      : state.activeView === 'agent' ? <AgentView trajectory={agentTurns} selectedNodeId={state.selectedNodeId} onSelectNode={(nodeId) => dispatch({ type: 'node/selected', nodeId })} artifactUrl={artifactUrl} />
        : state.activeView === 'context' ? <ContextView frame={contextFrame} onSelectSequence={(sequence) => dispatch({ type: 'node/selected', nodeId: `context:${sequence}` })} artifactUrl={artifactUrl} />
          : <EvidenceView index={evidenceIndex} selectedRef={state.selectedNodeId} onSelectRef={(ref) => dispatch({ type: 'node/selected', nodeId: ref })} artifactUrl={artifactUrl} />}
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

/** Builds only declared typed links from projection refs; it never examines answer prose. */
function evidenceFromProblems(problems: BusinessProblem[]): EvidenceIndex {
  const nodes = new Map<string, EvidenceNode>();
  const relations: EvidenceIndex['relations'] = [];
  for (const problem of problems) for (const node of problem.nodes) {
    if (node.kind !== 'claim' && node.kind !== 'decision' && node.kind !== 'verified-result') continue;
    const reference = node.id;
    nodes.set(reference, { ref: reference, type: node.kind === 'claim' ? 'claim' : node.kind === 'decision' ? 'decision' : 'result', label: node.title, source: node.source, integrity: node.status === 'unavailable' ? 'unavailable' : node.kind === 'verified-result' ? 'verified' : 'declared', producing_sequence: node.source_sequence, consumers: node.refs.length, artifact_ref: null, unavailable_reason: node.unavailable_reason });
    for (const ref of node.refs) {
      if (!nodes.has(ref)) nodes.set(ref, { ref, type: ref.startsWith('result:') ? 'result' : 'evidence', label: ref, source: 'observed', integrity: 'verified', producing_sequence: null, consumers: 1, artifact_ref: ref.startsWith('artifact:') ? ref : null, unavailable_reason: null });
      relations.push({ from_ref: reference, to_ref: ref, relation: node.kind === 'claim' ? 'supported by' : 'produced' });
    }
  }
  return { nodes: [...nodes.values()], relations };
}

function pageMetadata<T>(page: ProjectionPage<T>) {
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
