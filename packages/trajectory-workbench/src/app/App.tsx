import { useEffect, useReducer, useRef, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type { AgentTurn, BusinessNode, BusinessProblem, ContextFrame, EvidenceIndex, ProjectionPage, RunSummary } from '../api/types';
import { Inspector } from '../components/layout/Inspector';
import { OverviewTimeline } from '../components/layout/OverviewTimeline';
import { RunExplorer } from '../components/layout/RunExplorer';
import { RunHeader } from '../components/layout/RunHeader';
import { WorkbenchShell } from '../components/layout/WorkbenchShell';
import { initialWorkbenchState, workbenchReducer, type WorkbenchView } from '../state/workbench';
import { BusinessView } from '../views/BusinessView';
import { AgentView } from '../views/AgentView';
import { ContextView } from '../views/ContextView';
import { EvidenceView } from '../views/EvidenceView';
import { ApiError } from '../api/client';
import { AsyncState, type AsyncStateName } from '../components/common/AsyncState';
import { readThemePreference, saveThemePreference, systemTheme, type ResolvedTheme } from '../design/theme';

const api = new TrajectoryApiClient();

/** Data ownership begins here; the Task 2 shell supplies the visual regions. */
type AppClient = Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> & Partial<Pick<TrajectoryApiClient, 'getAgentPage' | 'getContextFrame' | 'getEvidenceIndex' | 'artifactUrl'>>;
type SelectedBusinessEntity = { problem: BusinessProblem; node: BusinessNode | null };

export function App({ client = api }: { client?: AppClient }) {
  const [state, dispatch] = useReducer(workbenchReducer, initialWorkbenchState);
  const [themePreference, setThemePreference] = useState<ResolvedTheme | null>(readThemePreference);
  const [activeTheme, setActiveTheme] = useState<ResolvedTheme>(() => themePreference ?? systemTheme());
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runListState, setRunListState] = useState<AsyncStateName>('loading');
  const [runListDiagnostic, setRunListDiagnostic] = useState<string | null>(null);
  const [runListAttempt, setRunListAttempt] = useState(0);
  const [pageAttempts, setPageAttempts] = useState<Record<WorkbenchView, number>>({ business: 0, agent: 0, context: 0, evidence: 0 });
  const [pageErrors, setPageErrors] = useState<Partial<Record<WorkbenchView, unknown>>>({});
  const [problems, setProblems] = useState<BusinessProblem[]>([]);
  const [agentTurns, setAgentTurns] = useState<AgentTurn[]>([]);
  const [contextFrame, setContextFrame] = useState<ContextFrame | null>(null);
  const [contextSequence, setContextSequence] = useState<number | null>(null);
  const [evidenceIndex, setEvidenceIndex] = useState<EvidenceIndex | null>(null);
  const [businessPage, setBusinessPage] = useState<Pick<ProjectionPage<BusinessProblem>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const loadingOlder = useRef(false);
  const failedOlderCursor = useRef<string | null>(null);
  const businessPageRef = useRef<Pick<ProjectionPage<BusinessProblem>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const deepLinkNode = useRef(new URLSearchParams(window.location.search).get('node'));

  useEffect(() => {
    document.documentElement.dataset.theme = activeTheme;
  }, [activeTheme]);

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!media) return;
    const update = () => {
      if (themePreference === null) setActiveTheme(media.matches ? 'dark' : 'light');
    };
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [themePreference]);

  const toggleTheme = () => {
    const nextTheme: ResolvedTheme = activeTheme === 'dark' ? 'light' : 'dark';
    setThemePreference(nextTheme);
    setActiveTheme(nextTheme);
    saveThemePreference(nextTheme);
    dispatch({ type: 'theme/changed', theme: nextTheme });
  };

  useEffect(() => {
    const selectedNode = deepLinkNode.current;
    if (!selectedNode) return;
    const sequence = contextSequenceFromNodeId(selectedNode);
    if (sequence !== null) {
      setContextSequence(sequence);
      dispatch({ type: 'view/selected', view: 'context' });
    }
    dispatch({ type: 'node/selected', nodeId: selectedNode });
  }, []);

  useEffect(() => {
    if (!state.selectedNodeId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('node', state.selectedNodeId);
    window.history.replaceState(null, '', url);
  }, [state.selectedNodeId]);

  useEffect(() => {
    const controller = new AbortController();
    setRunListState('loading');
    setRunListDiagnostic(null);
    void client.listRuns(controller.signal).then(({ items }) => {
      setRuns(items);
      setRunListState(items.length === 0 ? 'empty' : 'ready');
      dispatch({ type: 'run/selected', runId: items[0]?.analysis_id ?? null });
      if (deepLinkNode.current) dispatch({ type: 'node/selected', nodeId: deepLinkNode.current });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setRuns([]);
      setRunListState(error instanceof ApiError && error.status === 501 ? 'unsupported' : 'network-error');
      setRunListDiagnostic(error instanceof Error ? error.message : null);
    });
    return () => controller.abort();
  }, [client, runListAttempt]);

  useEffect(() => {
    if (!state.selectedRunId) return;
    const controller = new AbortController();
    setPageErrors((errors) => ({ ...errors, business: null }));
    dispatch({ type: 'page/requested', view: 'business' });
    void client.getBusinessPage(state.selectedRunId, undefined, controller.signal).then((page) => {
      setProblems(page.items);
      failedOlderCursor.current = null;
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/loaded', view: 'business', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setProblems([]);
      failedOlderCursor.current = null;
      businessPageRef.current = { older_cursor: null, has_older: false };
      setBusinessPage({ older_cursor: null, has_older: false });
      setPageErrors((errors) => ({ ...errors, business: error }));
      dispatch({ type: 'page/failed', view: 'business', message: pageErrorMessage(error, 'Unable to load business trajectory.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.business, state.selectedRunId]);

  useEffect(() => {
    if (state.activeView !== 'agent' || !state.selectedRunId || !client.getAgentPage) return;
    const controller = new AbortController();
    setPageErrors((errors) => ({ ...errors, agent: null }));
    dispatch({ type: 'page/requested', view: 'agent' });
    void client.getAgentPage(state.selectedRunId, undefined, controller.signal).then((page) => {
      setAgentTurns(page.items);
      dispatch({ type: 'page/loaded', view: 'agent', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setPageErrors((errors) => ({ ...errors, agent: error }));
      dispatch({ type: 'page/failed', view: 'agent', message: pageErrorMessage(error, 'Unable to load agent trajectory.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.agent, state.activeView, state.selectedRunId]);

  const selectedProblem = problems.find((problem) => problem.id === state.selectedNodeId || problem.turn_id === state.selectedNodeId || problem.nodes.some((node) => node.id === state.selectedNodeId)) ?? null;
  const selectedEntity: SelectedBusinessEntity | null = selectedProblem
    ? { problem: selectedProblem, node: selectedProblem.nodes.find((node) => node.id === state.selectedNodeId) ?? null }
    : null;
  const selectedRun = runs.find((run) => run.analysis_id === state.selectedRunId) ?? null;

  useEffect(() => {
    if (state.activeView !== 'context') return;
    // A scrubber selection owns its sequence. Only an external trajectory
    // selection should derive a new context sequence from the business page.
    if (state.selectedNodeId?.startsWith('context:')) return;
    const sequence = selectedEntity?.node?.source_sequence ?? selectedEntity?.problem.source_sequence ?? selectedRun?.last_sequence ?? null;
    setContextSequence(sequence && sequence >= 1 ? sequence : null);
  }, [state.activeView, state.selectedNodeId, state.selectedRunId, selectedEntity?.node?.source_sequence, selectedEntity?.problem.source_sequence, selectedRun?.last_sequence]);

  useEffect(() => {
    if (state.activeView !== 'context' || !state.selectedRunId || !client.getContextFrame) return;
    const sequence = contextSequence;
    if (!sequence || sequence < 1) return;
    const controller = new AbortController();
    setPageErrors((errors) => ({ ...errors, context: null }));
    dispatch({ type: 'page/requested', view: 'context' });
    void client.getContextFrame(state.selectedRunId, sequence, controller.signal).then((frame) => {
      setContextFrame(frame);
      dispatch({ type: 'page/loaded', view: 'context', page: { firstSequence: frame.source_sequence, lastSequence: frame.source_sequence, hasOlder: false } });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setContextFrame(null);
      setPageErrors((errors) => ({ ...errors, context: error }));
      dispatch({ type: 'page/failed', view: 'context', message: pageErrorMessage(error, 'Unable to load context frame.') });
    });
    return () => controller.abort();
  }, [client, contextSequence, pageAttempts.context, state.activeView, state.selectedRunId]);

  useEffect(() => {
    if (state.activeView !== 'evidence' || !state.selectedRunId || !client.getEvidenceIndex) return;
    const controller = new AbortController();
    setPageErrors((errors) => ({ ...errors, evidence: null }));
    dispatch({ type: 'page/requested', view: 'evidence' });
    void client.getEvidenceIndex(state.selectedRunId, controller.signal).then((index) => {
      setEvidenceIndex(index);
      dispatch({ type: 'page/loaded', view: 'evidence', page: { firstSequence: null, lastSequence: null, hasOlder: false } });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setEvidenceIndex(null);
      setPageErrors((errors) => ({ ...errors, evidence: error }));
      dispatch({ type: 'page/failed', view: 'evidence', message: pageErrorMessage(error, 'Unable to load evidence projection.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.evidence, state.activeView, state.selectedRunId]);

  const selectTurn = (turnId: string) => dispatch({ type: 'node/selected', nodeId: turnId });
  const loadOlder = (cursor: string) => {
    const runId = state.selectedRunId;
    const page = businessPageRef.current;
    if (!runId || !page.has_older || !cursor || loadingOlder.current) return;
    loadingOlder.current = true;
    setPageErrors((errors) => ({ ...errors, business: null }));
    dispatch({ type: 'page/requested', view: 'business' });
    void client.getBusinessPage(runId, cursor).then((page) => {
      setProblems((current) => prependProblems(page.items, current));
      failedOlderCursor.current = null;
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/prepended', view: 'business', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      failedOlderCursor.current = cursor;
      setPageErrors((errors) => ({ ...errors, business: error }));
      dispatch({ type: 'page/failed', view: 'business', message: pageErrorMessage(error, 'Unable to load older business trajectory.') });
    })
      .finally(() => { loadingOlder.current = false; });
  };
  const requestOlder = () => {
    const cursor = businessPageRef.current.older_cursor;
    if (cursor) loadOlder(cursor);
  };

  const artifactUrl = (ref: string) => client.artifactUrl ? client.artifactUrl(state.selectedRunId ?? '', ref) : '#';
  const pageError = pageErrors[state.activeView];
  const pageState: AsyncStateName = state.pageStatus[state.activeView] === 'loading' ? 'loading'
    : pageError instanceof ApiError && pageError.status === 501 ? 'unsupported'
      : state.pageStatus[state.activeView] === 'failed' ? 'network-error' : 'ready';
  const viewState: AsyncStateName = selectedRun?.status === 'corrupt' ? 'corrupt' : pageState;
  const retryActivePage = () => {
    const cursor = state.activeView === 'business' ? failedOlderCursor.current : null;
    if (cursor) {
      loadOlder(cursor);
      return;
    }
    setPageAttempts((attempts) => ({ ...attempts, [state.activeView]: attempts[state.activeView] + 1 }));
  };
  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`} aria-busy={viewState === 'loading'}>
    {selectedRun?.status === 'partial' ? <AsyncState state="partial" diagnostic={selectedRun.diagnostic} /> : null}
    <AsyncState state={viewState} diagnostic={state.pageError[state.activeView]} onRetry={retryActivePage}>
    {state.activeView === 'business' ? <BusinessView problems={problems} state={state} dispatch={dispatch} hasOlder={businessPage.has_older} onRequestOlder={requestOlder} />
      : state.activeView === 'agent' ? <AgentView trajectory={agentTurns} selectedNodeId={state.selectedNodeId} onSelectNode={(nodeId) => dispatch({ type: 'node/selected', nodeId })} artifactUrl={artifactUrl} />
        : state.activeView === 'context' ? <ContextView frame={contextFrame} onSelectSequence={(sequence) => { setContextSequence(sequence); dispatch({ type: 'node/selected', nodeId: `context:${sequence}` }); }} artifactUrl={artifactUrl} />
          : <EvidenceView index={evidenceIndex} selectedRefs={selectedEntity?.node?.refs ?? (state.selectedNodeId ? [state.selectedNodeId] : [])} onSelectRef={(ref) => dispatch({ type: 'node/selected', nodeId: ref })} artifactUrl={artifactUrl} />}
    </AsyncState>
  </section>;

  return <div className="workbench-bootstrap" aria-label="Trajectory workbench" data-view={state.activeView}>
    <WorkbenchShell
      header={<RunHeader run={selectedRun} activeView={state.activeView} onViewSelect={(view) => dispatch({ type: 'view/selected', view })} theme={activeTheme} onThemeToggle={toggleTheme} />}
      explorer={<AsyncState state={runListState} diagnostic={runListDiagnostic} onRetry={() => setRunListAttempt((attempt) => attempt + 1)}>
        <RunExplorer runs={runs} selectedRunId={state.selectedRunId} onSelectRun={(runId) => dispatch({ type: 'run/selected', runId })} />
      </AsyncState>}
      timeline={<OverviewTimeline problems={problems} selectedTurnId={selectedProblem?.turn_id ?? state.selectedNodeId} onSelectTurn={selectTurn} onFocusRange={(range) => dispatch({ type: 'timeline/focused', range })} />}
      content={content}
      inspector={<Inspector entity={selectedEntity} artifactUrl={artifactUrl} />}
      focusedTurnId={selectedProblem?.turn_id ?? state.selectedNodeId}
    />
  </div>;
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

function contextSequenceFromNodeId(nodeId: string): number | null {
  const match = /^context:([1-9]\d*)$/.exec(nodeId);
  if (!match) return null;
  const sequence = Number(match[1]);
  return Number.isSafeInteger(sequence) ? sequence : null;
}

function pageErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
