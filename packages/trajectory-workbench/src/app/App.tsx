import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type { AgentTurn, BusinessCausalRow, ContextFrame, EvidenceIndex, ExecutionSlice, ProjectionPage, RunSummary } from '../api/types';
import { prependBusinessRows, problemsFromBusinessRows } from '../api/business';
import { AuditInspector } from '../components/audit/AuditInspector';
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
import { resolveAuditSelection } from '../audit/selection';
import { buildAuditInspectorModel, type AuditPanel } from '../audit/inspector-model';
import { AsyncState, type AsyncStateName } from '../components/common/AsyncState';
import { readThemePreference, saveThemePreference, systemTheme, type ResolvedTheme } from '../design/theme';

const api = new TrajectoryApiClient();

/** Data ownership begins here; the Task 2 shell supplies the visual regions. */
type AppClient = Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> & Partial<Pick<TrajectoryApiClient, 'getAgentPage' | 'getContextFrame' | 'getExecutionSlice' | 'getEvidenceIndex' | 'artifactUrl'>>;

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
  const [businessRows, setBusinessRows] = useState<BusinessCausalRow[]>([]);
  const problems = useMemo(() => problemsFromBusinessRows(businessRows), [businessRows]);
  const [agentTurns, setAgentTurns] = useState<AgentTurn[]>([]);
  const [contextFrame, setContextFrame] = useState<ContextFrame | null>(null);
  const [contextSequence, setContextSequence] = useState<number | null>(null);
  const [executionSlice, setExecutionSlice] = useState<ExecutionSlice | null>(null);
  const [executionSliceState, setExecutionSliceState] = useState<AsyncStateName>('idle');
  const [executionSliceDiagnostic, setExecutionSliceDiagnostic] = useState<string | null>(null);
  const [executionSliceAttempt, setExecutionSliceAttempt] = useState(0);
  const [evidenceIndex, setEvidenceIndex] = useState<EvidenceIndex | null>(null);
  const [businessPage, setBusinessPage] = useState<Pick<ProjectionPage<BusinessCausalRow>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const [olderState, setOlderState] = useState<'idle' | 'loading' | 'failed'>('idle');
  const [olderError, setOlderError] = useState<string | null>(null);
  const loadingOlder = useRef(false);
  const failedOlderCursor = useRef<string | null>(null);
  const businessPageRef = useRef<Pick<ProjectionPage<BusinessCausalRow>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const olderRequestRef = useRef<{ controller: AbortController; runId: string; cursor: string } | null>(null);
  const selectedRunIdRef = useRef<string | null>(state.selectedRunId);
  const contextSequenceRef = useRef<number | null>(contextSequence);
  const deepLinkNode = useRef(new URLSearchParams(window.location.search).get('node'));

  selectedRunIdRef.current = state.selectedRunId;
  contextSequenceRef.current = contextSequence;

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
    const requestedRunId = state.selectedRunId;
    const controller = new AbortController();
    olderRequestRef.current?.controller.abort();
    olderRequestRef.current = null;
    loadingOlder.current = false;
    setBusinessRows([]);
    setPageErrors((errors) => ({ ...errors, business: null }));
    dispatch({ type: 'page/requested', view: 'business' });
    void client.getBusinessPage(requestedRunId, undefined, controller.signal).then((page) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      if (page.analysis_id !== requestedRunId) {
        throw new Error('Business projection response identity does not match the requested run.');
      }
      setBusinessRows(page.items);
      failedOlderCursor.current = null;
      setOlderState('idle');
      setOlderError(null);
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/loaded', view: 'business', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      setBusinessRows([]);
      failedOlderCursor.current = null;
      setOlderState('idle');
      setOlderError(null);
      businessPageRef.current = { older_cursor: null, has_older: false };
      setBusinessPage({ older_cursor: null, has_older: false });
      setPageErrors((errors) => ({ ...errors, business: error }));
      dispatch({ type: 'page/failed', view: 'business', message: pageErrorMessage(error, 'Unable to load business trajectory.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.business, state.selectedRunId]);

  useEffect(() => {
    const needsAgent = state.activeView === 'agent';
    if (!needsAgent || !state.selectedRunId || !client.getAgentPage) return;
    const requestedRunId = state.selectedRunId;
    const controller = new AbortController();
    setPageErrors((errors) => ({ ...errors, agent: null }));
    dispatch({ type: 'page/requested', view: 'agent' });
    void client.getAgentPage(requestedRunId, undefined, controller.signal).then((page) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      if (page.analysis_id !== requestedRunId) {
        throw new Error('Agent projection response identity does not match the requested run.');
      }
      setAgentTurns(page.items);
      dispatch({ type: 'page/loaded', view: 'agent', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      setPageErrors((errors) => ({ ...errors, agent: error }));
      dispatch({ type: 'page/failed', view: 'agent', message: pageErrorMessage(error, 'Unable to load agent trajectory.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.agent, state.activeView, state.selectedNodeId, state.selectedRunId]);

  const auditSelection = resolveAuditSelection(problems, agentTurns, state.selectedNodeId);
  const auditSequence = auditSelection?.sequence ?? null;
  const auditSequenceRef = useRef<number | null>(auditSequence);
  auditSequenceRef.current = auditSequence;
  const focusedProblem = problems.find((problem) => problem.id === state.focusedProblemId) ?? null;
  const selectedRun = runs.find((run) => run.analysis_id === state.selectedRunId) ?? null;
  const auditInspectorModel = auditSelection ? buildAuditInspectorModel({
    selection: auditSelection,
    evidenceIndex,
    context: contextFrame,
  }) : null;
  const hasAuditSelection = Boolean(auditSelection);
  const auditArtifactKey = auditSelection?.artifactRefs.join('\0') ?? '';

  useEffect(() => {
    if (!auditSequence || !state.selectedRunId || !client.getExecutionSlice) {
      setExecutionSlice(null);
      setExecutionSliceState('idle');
      setExecutionSliceDiagnostic(null);
      return;
    }
    const requestedRunId = state.selectedRunId;
    const requestedSequence = auditSequence;
    const controller = new AbortController();
    setExecutionSlice(null);
    setExecutionSliceState('loading');
    setExecutionSliceDiagnostic(null);
    void client.getExecutionSlice(requestedRunId, requestedSequence, controller.signal).then((slice) => {
      if (
        controller.signal.aborted
        || selectedRunIdRef.current !== requestedRunId
        || auditSequenceRef.current !== requestedSequence
      ) return;
      if (slice.analysis_id !== requestedRunId || slice.source_sequence !== requestedSequence) {
        throw new Error('Execution slice response identity does not match the requested selection.');
      }
      setExecutionSlice(slice);
      setExecutionSliceState('ready');
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || selectedRunIdRef.current !== requestedRunId
        || auditSequenceRef.current !== requestedSequence
      ) return;
      setExecutionSlice(null);
      setExecutionSliceState(error instanceof ApiError && error.status === 501 ? 'unsupported' : 'network-error');
      setExecutionSliceDiagnostic(pageErrorMessage(error, 'Unable to load execution linkage.'));
    });
    return () => controller.abort();
  }, [auditSequence, client, executionSliceAttempt, state.selectedRunId]);

  useEffect(() => {
    if (!auditSelection && state.activeView !== 'context') return;
    // A scrubber selection owns its sequence. Only an external trajectory
    // selection should derive a new context sequence from the business page.
    if (state.selectedNodeId?.startsWith('context:')) return;
    const sequence = auditSelection?.sequence ?? (state.activeView === 'context' ? selectedRun?.last_sequence ?? null : null);
    setContextSequence(sequence && sequence >= 1 ? sequence : null);
  }, [auditSelection?.sequence, state.activeView, state.selectedNodeId, state.selectedRunId, selectedRun?.last_sequence]);

  useEffect(() => {
    const needsContext = state.activeView === 'context' || hasAuditSelection;
    if (!needsContext || !state.selectedRunId || !client.getContextFrame) return;
    const requestedRunId = state.selectedRunId;
    const sequence = contextSequence;
    if (!sequence || sequence < 1) return;
    const requestedSequence = sequence;
    const controller = new AbortController();
    setContextFrame(null);
    setPageErrors((errors) => ({ ...errors, context: null }));
    dispatch({ type: 'page/requested', view: 'context' });
    void client.getContextFrame(requestedRunId, requestedSequence, controller.signal).then((frame) => {
      if (
        controller.signal.aborted
        || selectedRunIdRef.current !== requestedRunId
        || contextSequenceRef.current !== requestedSequence
      ) return;
      if (frame.source_sequence !== requestedSequence) {
        throw new Error('Context projection response sequence does not match the requested sequence.');
      }
      setContextFrame(frame);
      dispatch({ type: 'page/loaded', view: 'context', page: { firstSequence: frame.source_sequence, lastSequence: frame.source_sequence, hasOlder: false } });
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || selectedRunIdRef.current !== requestedRunId
        || contextSequenceRef.current !== requestedSequence
      ) return;
      setContextFrame(null);
      setPageErrors((errors) => ({ ...errors, context: error }));
      dispatch({ type: 'page/failed', view: 'context', message: pageErrorMessage(error, 'Unable to load context frame.') });
    });
    return () => controller.abort();
  }, [client, contextSequence, hasAuditSelection, pageAttempts.context, state.activeView, state.selectedRunId]);

  useEffect(() => {
    const needsEvidence = state.activeView === 'evidence' || auditArtifactKey.length > 0;
    if (!needsEvidence || !state.selectedRunId || !client.getEvidenceIndex) return;
    const requestedRunId = state.selectedRunId;
    const controller = new AbortController();
    setEvidenceIndex(null);
    setPageErrors((errors) => ({ ...errors, evidence: null }));
    dispatch({ type: 'page/requested', view: 'evidence' });
    void client.getEvidenceIndex(requestedRunId, controller.signal).then((index) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      if (index.analysis_id !== requestedRunId) {
        throw new Error('Evidence projection response identity does not match the requested run.');
      }
      setEvidenceIndex(index);
      dispatch({ type: 'page/loaded', view: 'evidence', page: { firstSequence: null, lastSequence: null, hasOlder: false } });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || selectedRunIdRef.current !== requestedRunId) return;
      setEvidenceIndex(null);
      setPageErrors((errors) => ({ ...errors, evidence: error }));
      dispatch({ type: 'page/failed', view: 'evidence', message: pageErrorMessage(error, 'Unable to load evidence projection.') });
    });
    return () => controller.abort();
  }, [auditArtifactKey, client, pageAttempts.evidence, state.activeView, state.selectedRunId]);

  const selectTurn = (turnId: string) => dispatch({ type: 'node/selected', nodeId: turnId });
  const selectSequence = (sequence: number) => {
    const matchingNode = problems.flatMap((problem) => problem.nodes).find((node) => node.source_sequence === sequence);
    if (matchingNode) {
      dispatch({ type: 'node/selected', nodeId: matchingNode.id });
      return;
    }
    const matchingProblem = problems.find((problem) => problem.source_sequence === sequence);
    if (matchingProblem) {
      dispatch({ type: 'node/selected', nodeId: matchingProblem.id });
      return;
    }
    setContextSequence(sequence);
    dispatch({ type: 'node/selected', nodeId: `context:${sequence}` });
  };
  const loadOlder = (cursor: string) => {
    const runId = state.selectedRunId;
    const page = businessPageRef.current;
    if (!runId || !page.has_older || !cursor || loadingOlder.current) return;
    const controller = new AbortController();
    const request = { controller, runId, cursor };
    olderRequestRef.current = request;
    loadingOlder.current = true;
    setOlderState('loading');
    setOlderError(null);
    setPageErrors((errors) => ({ ...errors, business: null }));
    void client.getBusinessPage(runId, cursor, controller.signal).then((page) => {
      if (
        controller.signal.aborted
        || olderRequestRef.current !== request
        || selectedRunIdRef.current !== runId
      ) return;
      if (page.analysis_id !== runId) {
        throw new Error('Business projection response identity does not match the requested run.');
      }
      setBusinessRows((current) => prependBusinessRows(page.items, current));
      failedOlderCursor.current = null;
      setOlderState('idle');
      setOlderError(null);
      businessPageRef.current = page;
      setBusinessPage(page);
      dispatch({ type: 'page/prepended', view: 'business', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || olderRequestRef.current !== request
        || selectedRunIdRef.current !== runId
      ) return;
      failedOlderCursor.current = cursor;
      if (error instanceof ApiError && error.status === 501) {
        setOlderState('idle');
        setOlderError(null);
        setPageErrors((errors) => ({ ...errors, business: error }));
        dispatch({ type: 'page/failed', view: 'business', message: pageErrorMessage(error, 'Unable to load older business trajectory.') });
        return;
      }
      setOlderState('failed');
      setOlderError(pageErrorMessage(error, 'Unable to load older business trajectory.'));
    })
      .finally(() => {
        if (olderRequestRef.current !== request) return;
        olderRequestRef.current = null;
        loadingOlder.current = false;
      });
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
  const retryInspectorPanel = (panel: AuditPanel) => {
    if (panel === 'execution') {
      setExecutionSliceAttempt((attempt) => attempt + 1);
      return;
    }
    const view = panel === 'context' ? 'context' : panel === 'evidence' ? 'evidence' : null;
    if (!view) return;
    setPageAttempts((attempts) => ({ ...attempts, [view]: attempts[view] + 1 }));
  };
  const inspectorPanelStates: Partial<Record<AuditPanel, AsyncStateName>> = {
    evidence: projectionPanelState('evidence', state, pageErrors),
    context: projectionPanelState('context', state, pageErrors),
    execution: executionSliceState,
  };
  const inspectorPanelDiagnostics: Partial<Record<AuditPanel, string | null>> = {
    evidence: state.pageError.evidence,
    context: state.pageError.context,
    execution: executionSliceDiagnostic,
  };
  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`} aria-busy={viewState === 'loading'}>
    {selectedRun?.status === 'partial' ? <AsyncState state="partial" diagnostic={selectedRun.diagnostic} /> : null}
    <AsyncState state={viewState} diagnostic={state.pageError[state.activeView]} onRetry={retryActivePage}>
    {state.activeView === 'business' ? <BusinessView
      problems={problems}
      state={state}
      dispatch={dispatch}
      hasOlder={businessPage.has_older}
      onRequestOlder={requestOlder}
      olderState={olderState}
      olderError={olderError}
      onRetryOlder={() => {
        const cursor = failedOlderCursor.current;
        if (cursor) loadOlder(cursor);
      }}
    />
      : state.activeView === 'agent' ? <AgentView trajectory={agentTurns} selectedNodeId={state.selectedNodeId} onSelectNode={(nodeId) => dispatch({ type: 'node/selected', nodeId })} artifactUrl={artifactUrl} />
        : state.activeView === 'context' ? <ContextView frame={contextFrame} onSelectSequence={(sequence) => { setContextSequence(sequence); dispatch({ type: 'node/selected', nodeId: `context:${sequence}` }); }} artifactUrl={artifactUrl} />
          : <EvidenceView index={evidenceIndex} selectedRefs={auditSelection?.artifactRefs ?? (state.selectedNodeId ? [state.selectedNodeId] : [])} onSelectRef={(ref) => dispatch({ type: 'node/selected', nodeId: ref })} artifactUrl={artifactUrl} />}
    </AsyncState>
  </section>;

  return <div className="workbench-bootstrap" aria-label="Trajectory workbench" data-view={state.activeView}>
    <WorkbenchShell
      header={<RunHeader run={selectedRun} activeView={state.activeView} onViewSelect={(view) => dispatch({ type: 'view/selected', view })} theme={activeTheme} onThemeToggle={toggleTheme} />}
      explorer={<AsyncState state={runListState} diagnostic={runListDiagnostic} onRetry={() => setRunListAttempt((attempt) => attempt + 1)}>
        <RunExplorer runs={runs} selectedRunId={state.selectedRunId} problems={problems} focusedProblemId={state.focusedProblemId} onSelectRun={(runId) => dispatch({ type: 'run/selected', runId })} onFocusProblem={(problemId) => dispatch({ type: 'problem/focused', problemId })} />
      </AsyncState>}
      timeline={<OverviewTimeline problems={problems} selectedTurnId={auditSelection?.turnId ?? focusedProblem?.turn_id ?? state.selectedNodeId} onSelectTurn={selectTurn} onFocusRange={(range) => dispatch({ type: 'timeline/focused', range })} />}
      content={content}
      inspector={<AuditInspector
        model={auditInspectorModel}
        executionSlice={executionSlice}
        artifactUrl={artifactUrl}
        onSelectSequence={selectSequence}
        panelStates={inspectorPanelStates}
        panelDiagnostics={inspectorPanelDiagnostics}
        onRetryPanel={retryInspectorPanel}
        runStatus={selectedRun?.status}
        runDiagnostic={selectedRun?.diagnostic}
      />}
      focusedTurnId={auditSelection?.turnId ?? focusedProblem?.turn_id ?? state.selectedNodeId}
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

function contextSequenceFromNodeId(nodeId: string): number | null {
  const match = /^context:([1-9]\d*)$/.exec(nodeId);
  if (!match) return null;
  const sequence = Number(match[1]);
  return Number.isSafeInteger(sequence) ? sequence : null;
}

function pageErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function projectionPanelState(
  view: WorkbenchView,
  state: { pageStatus: Record<WorkbenchView, string> },
  pageErrors: Partial<Record<WorkbenchView, unknown>>,
): AsyncStateName {
  if (state.pageStatus[view] === 'loading') return 'loading';
  const error = pageErrors[view];
  if (error instanceof ApiError && error.status === 501) return 'unsupported';
  if (state.pageStatus[view] === 'failed') return 'network-error';
  return 'ready';
}
