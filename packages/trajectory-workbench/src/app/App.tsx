import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { TrajectoryApiClient } from '../api/client';
import type {
  AgentEventRow, AgentPageRequest, AgentTurn, BusinessCausalRow, ContextFrame,
  ContextFrameSummary, ContextPageRequest, EvidenceIndex,
  EvidencePageRequest, EvidenceRecord, ExecutionSlice, ProjectionPage, RunSummary,
} from '../api/types';
import { prependBusinessRows, problemsFromBusinessRows } from '../api/business';
import { pageRequestKey, prependOperationalPage, type OperationalPageState } from '../api/operational-page';
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

/** Transitional clients may still return nested Agent turns while fixtures migrate to flat rows. */
type AppClient = Pick<TrajectoryApiClient, 'listRuns' | 'getBusinessPage'> & {
  getAgentPage?: (
    id: string, request?: AgentPageRequest, signal?: AbortSignal,
  ) => Promise<ProjectionPage<AgentEventRow | AgentTurn>>;
  getContextPage?: (
    id: string, request?: ContextPageRequest, signal?: AbortSignal,
  ) => Promise<ProjectionPage<ContextFrameSummary>>;
  getEvidencePage?: (
    id: string, request?: EvidencePageRequest, signal?: AbortSignal,
  ) => Promise<ProjectionPage<EvidenceRecord>>;
} & Partial<Pick<TrajectoryApiClient, 'getContextFrame' | 'getExecutionSlice' | 'getEvidenceIndex' | 'artifactUrl'>>;

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
  const [agentPageState, setAgentPageState] = useState<OperationalPageState<AgentEventRow | AgentTurn>>({
    items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey: '',
  });
  const agentRows = useMemo(() => agentPageState.page?.analysis_id === state.selectedRunId
    ? agentPageState.items.filter((item): item is AgentEventRow => 'parent_id' in item && 'kind' in item)
    : [], [agentPageState, state.selectedRunId]);
  const agentTurns = useMemo(() => agentPageState.page?.analysis_id === state.selectedRunId
    ? agentPageState.items.filter((item): item is AgentTurn => 'steps' in item && 'source_sequences' in item)
    : [], [agentPageState, state.selectedRunId]);
  const [contextPageState, setContextPageState] = useState<OperationalPageState<ContextFrameSummary>>({
    items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey: '',
  });
  const contextSummaries = useMemo(() => contextPageState.page?.analysis_id === state.selectedRunId
    ? contextPageState.items : [], [contextPageState, state.selectedRunId]);
  const [contextFrame, setContextFrame] = useState<ContextFrame | null>(null);
  const [contextSequence, setContextSequence] = useState<number | null>(null);
  const [contextDetailState, setContextDetailState] = useState<'idle' | 'loading' | 'ready' | 'failed'>('idle');
  const [contextDetailError, setContextDetailError] = useState<string | null>(null);
  const [contextDetailAttempt, setContextDetailAttempt] = useState(0);
  const [executionSlice, setExecutionSlice] = useState<ExecutionSlice | null>(null);
  const [executionSliceState, setExecutionSliceState] = useState<AsyncStateName>('idle');
  const [executionSliceDiagnostic, setExecutionSliceDiagnostic] = useState<string | null>(null);
  const [executionSliceAttempt, setExecutionSliceAttempt] = useState(0);
  const [evidencePageState, setEvidencePageState] = useState<OperationalPageState<EvidenceRecord>>({
    items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey: '',
  });
  const [legacyEvidenceIndex, setLegacyEvidenceIndex] = useState<EvidenceIndex | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<{
    analysisId: string;
    requestKey: string;
    items: EvidenceRecord[];
  } | null>(null);
  const evidenceIndex = useMemo<EvidenceIndex | null>(() => {
    const legacyRecords = legacyEvidenceIndex?.analysis_id === state.selectedRunId
      ? Object.values(legacyEvidenceIndex.records) : [];
    const pageRecords = evidencePageState.page?.analysis_id === state.selectedRunId
      ? evidencePageState.items : [];
    const selectedRecords = selectedEvidence?.analysisId === state.selectedRunId
      ? selectedEvidence.items : [];
    if (
      legacyEvidenceIndex?.analysis_id !== state.selectedRunId
      && evidencePageState.page?.analysis_id !== state.selectedRunId
      && selectedEvidence?.analysisId !== state.selectedRunId
    ) return null;
    return {
      analysis_id: state.selectedRunId,
      records: Object.fromEntries([...legacyRecords, ...pageRecords, ...selectedRecords]
        .map((record) => [record.reference, record])),
    };
  }, [evidencePageState, legacyEvidenceIndex, selectedEvidence, state.selectedRunId]);
  const [businessPage, setBusinessPage] = useState<Pick<ProjectionPage<BusinessCausalRow>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const [olderState, setOlderState] = useState<'idle' | 'loading' | 'failed'>('idle');
  const [olderError, setOlderError] = useState<string | null>(null);
  const loadingOlder = useRef(false);
  const failedOlderCursor = useRef<string | null>(null);
  const businessPageRef = useRef<Pick<ProjectionPage<BusinessCausalRow>, 'older_cursor' | 'has_older'>>({ older_cursor: null, has_older: false });
  const olderRequestRef = useRef<{ controller: AbortController; runId: string; cursor: string } | null>(null);
  const selectedRunIdRef = useRef<string | null>(state.selectedRunId);
  const operationalRequestKeyRef = useRef<Record<'agent' | 'context' | 'evidence', string>>({ agent: '', context: '', evidence: '' });
  const operationalBaseRequestKeyRef = useRef<Record<'agent' | 'context' | 'evidence', string>>({ agent: '', context: '', evidence: '' });
  const operationalOlderRequestRef = useRef<Record<'agent' | 'context' | 'evidence', { controller: AbortController; requestKey: string } | null>>({
    agent: null, context: null, evidence: null,
  });
  const contextDetailRequestKeyRef = useRef('');
  const executionRequestKeyRef = useRef('');
  const selectedEvidenceRequestKeyRef = useRef('');
  const deepLinkNode = useRef(new URLSearchParams(window.location.search).get('node'));

  selectedRunIdRef.current = state.selectedRunId;

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
    operationalOlderRequestRef.current.agent?.controller.abort();
    operationalOlderRequestRef.current.agent = null;
    if (!needsAgent || !state.selectedRunId || !client.getAgentPage) {
      operationalRequestKeyRef.current.agent = '';
      return;
    }
    const requestedRunId = state.selectedRunId;
    const filters = { ...state.pageFilters.agent };
    const request: AgentPageRequest = { filters };
    const requestKey = pageRequestKey(requestedRunId, 'agent', { filters: { ...filters } });
    const isNewIdentity = operationalBaseRequestKeyRef.current.agent !== requestKey;
    const showInitialLoading = isNewIdentity || agentPageState.page === null;
    const controller = new AbortController();
    operationalBaseRequestKeyRef.current.agent = requestKey;
    operationalRequestKeyRef.current.agent = requestKey;
    setAgentPageState((current) => isNewIdentity
      ? { items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey }
      : { ...current, olderState: 'idle', olderError: null, failedCursor: null, requestKey });
    setPageErrors((errors) => ({ ...errors, agent: null }));
    if (showInitialLoading) dispatch({ type: 'page/requested', view: 'agent' });
    void client.getAgentPage(requestedRunId, request, controller.signal).then((page) => {
      if (
        controller.signal.aborted
        || operationalRequestKeyRef.current.agent !== requestKey
        || page.analysis_id !== requestedRunId
      ) return;
      setAgentPageState((current) => ({
        items: isNewIdentity ? page.items : prependOperationalPage(current.items, page.items),
        page: isNewIdentity ? page : current.page ?? page,
        olderState: 'idle', olderError: null, failedCursor: null, requestKey,
      }));
      if (showInitialLoading) dispatch({ type: 'page/loaded', view: 'agent', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || operationalRequestKeyRef.current.agent !== requestKey) return;
      setPageErrors((errors) => ({ ...errors, agent: error }));
      if (showInitialLoading) dispatch({ type: 'page/failed', view: 'agent', message: pageErrorMessage(error, 'Unable to load agent trajectory.') });
    });
    return () => controller.abort();
  }, [client, pageAttempts.agent, state.activeView, state.pageFilters.agent, state.selectedRunId]);

  const auditSelection = resolveAuditSelection(problems, agentTurns, state.selectedNodeId);
  const auditSequence = auditSelection?.sequence ?? null;
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
    if (!state.selectedRunId || !client.getEvidencePage || auditArtifactKey.length === 0) {
      selectedEvidenceRequestKeyRef.current = '';
      setSelectedEvidence(null);
      return;
    }
    const requestedRunId = state.selectedRunId;
    const references = [...new Set(auditArtifactKey.split('\0'))].sort();
    const requestKeys = references.map((reference) => pageRequestKey(requestedRunId, 'evidence', {
      filters: { relevant_ref: reference },
    }));
    const requestKey = JSON.stringify(requestKeys);
    const controller = new AbortController();
    selectedEvidenceRequestKeyRef.current = requestKey;
    setSelectedEvidence((current) => current?.requestKey === requestKey ? current : null);
    void Promise.all(references.map((reference) => client.getEvidencePage!(requestedRunId, {
      filters: { relevant_ref: reference },
    }, controller.signal))).then((pages) => {
      if (
        controller.signal.aborted
        || selectedEvidenceRequestKeyRef.current !== requestKey
        || pages.some((page) => page.analysis_id !== requestedRunId)
      ) return;
      setSelectedEvidence({
        analysisId: requestedRunId,
        requestKey,
        items: pages.reduce<EvidenceRecord[]>((items, page) => prependOperationalPage(items, page.items), []),
      });
    }).catch(() => {
      if (controller.signal.aborted || selectedEvidenceRequestKeyRef.current !== requestKey) return;
      setSelectedEvidence((current) => current?.requestKey === requestKey ? null : current);
    });
    return () => controller.abort();
  }, [auditArtifactKey, client, pageAttempts.evidence, state.selectedRunId]);

  useEffect(() => {
    if (!auditSequence || !state.selectedRunId || !client.getExecutionSlice) {
      executionRequestKeyRef.current = '';
      setExecutionSlice(null);
      setExecutionSliceState('idle');
      setExecutionSliceDiagnostic(null);
      return;
    }
    const requestedRunId = state.selectedRunId;
    const requestedSequence = auditSequence;
    const requestKey = pageRequestKey(requestedRunId, 'agent', { filters: { at_sequence: requestedSequence } });
    const controller = new AbortController();
    executionRequestKeyRef.current = requestKey;
    setExecutionSlice(null);
    setExecutionSliceState('loading');
    setExecutionSliceDiagnostic(null);
    void client.getExecutionSlice(requestedRunId, requestedSequence, controller.signal).then((slice) => {
      if (
        controller.signal.aborted
        || executionRequestKeyRef.current !== requestKey
        || slice.analysis_id !== requestedRunId
        || slice.source_sequence !== requestedSequence
      ) return;
      setExecutionSlice(slice);
      setExecutionSliceState('ready');
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || executionRequestKeyRef.current !== requestKey
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
    if (!auditSelection && client.getContextPage) return;
    const sequence = auditSelection?.sequence ?? (state.activeView === 'context' ? selectedRun?.last_sequence ?? null : null);
    setContextSequence(sequence && sequence >= 1 ? sequence : null);
  }, [auditSelection?.sequence, client, state.activeView, state.selectedNodeId, state.selectedRunId, selectedRun?.last_sequence]);

  useEffect(() => {
    operationalOlderRequestRef.current.context?.controller.abort();
    operationalOlderRequestRef.current.context = null;
    if (state.activeView !== 'context' || !state.selectedRunId || !client.getContextPage) {
      operationalRequestKeyRef.current.context = '';
      return;
    }
    const requestedRunId = state.selectedRunId;
    const filters = { ...state.pageFilters.context };
    const request: ContextPageRequest = { filters };
    const requestKey = pageRequestKey(requestedRunId, 'context', { filters: { ...filters } });
    const isNewIdentity = operationalBaseRequestKeyRef.current.context !== requestKey;
    const showInitialLoading = isNewIdentity || contextPageState.page === null;
    const preserveExactSequence = hasAuditSelection || state.selectedNodeId?.startsWith('context:');
    const controller = new AbortController();
    operationalBaseRequestKeyRef.current.context = requestKey;
    operationalRequestKeyRef.current.context = requestKey;
    setContextPageState((current) => isNewIdentity
      ? { items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey }
      : { ...current, olderState: 'idle', olderError: null, failedCursor: null, requestKey });
    if (isNewIdentity) {
      setContextFrame(null);
      setContextDetailState('idle');
      setContextDetailError(null);
      if (!preserveExactSequence) setContextSequence(null);
    }
    setPageErrors((errors) => ({ ...errors, context: null }));
    if (showInitialLoading) dispatch({ type: 'page/requested', view: 'context' });
    void client.getContextPage(requestedRunId, request, controller.signal).then((page) => {
      if (
        controller.signal.aborted
        || operationalRequestKeyRef.current.context !== requestKey
        || page.analysis_id !== requestedRunId
      ) return;
      setContextPageState((current) => ({
        items: isNewIdentity ? page.items : prependOperationalPage(current.items, page.items),
        page: isNewIdentity ? page : current.page ?? page,
        olderState: 'idle', olderError: null, failedCursor: null, requestKey,
      }));
      if (showInitialLoading) dispatch({ type: 'page/loaded', view: 'context', page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || operationalRequestKeyRef.current.context !== requestKey) return;
      setPageErrors((errors) => ({ ...errors, context: error }));
      if (showInitialLoading) dispatch({ type: 'page/failed', view: 'context', message: pageErrorMessage(error, 'Unable to load context trajectory.') });
    });
    return () => controller.abort();
  }, [client, hasAuditSelection, pageAttempts.context, state.activeView, state.pageFilters.context, state.selectedNodeId, state.selectedRunId]);

  useEffect(() => {
    const needsContext = state.activeView === 'context' || hasAuditSelection;
    if (!needsContext || !state.selectedRunId || !client.getContextFrame) {
      contextDetailRequestKeyRef.current = '';
      return;
    }
    const requestedRunId = state.selectedRunId;
    const sequence = contextSequence;
    if (!sequence || sequence < 1) {
      contextDetailRequestKeyRef.current = '';
      setContextFrame(null);
      setContextDetailState('idle');
      setContextDetailError(null);
      return;
    }
    const requestedSequence = sequence;
    const requestKey = pageRequestKey(requestedRunId, 'context', { filters: { at_sequence: requestedSequence } });
    const detailOwnsPageStatus = state.activeView !== 'context' || !client.getContextPage;
    const controller = new AbortController();
    contextDetailRequestKeyRef.current = requestKey;
    setContextFrame(null);
    setContextDetailState('loading');
    setContextDetailError(null);
    if (detailOwnsPageStatus) setPageErrors((errors) => ({ ...errors, context: null }));
    if (detailOwnsPageStatus) dispatch({ type: 'page/requested', view: 'context' });
    void client.getContextFrame(requestedRunId, requestedSequence, controller.signal).then((frame) => {
      if (
        controller.signal.aborted
        || contextDetailRequestKeyRef.current !== requestKey
        || selectedRunIdRef.current !== requestedRunId
        || frame.source_sequence !== requestedSequence
      ) return;
      setContextFrame(frame);
      setContextDetailState('ready');
      setContextDetailError(null);
      if (detailOwnsPageStatus) {
        dispatch({ type: 'page/loaded', view: 'context', page: { firstSequence: frame.source_sequence, lastSequence: frame.source_sequence, hasOlder: false } });
      }
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || contextDetailRequestKeyRef.current !== requestKey
      ) return;
      setContextFrame(null);
      setContextDetailState('failed');
      setContextDetailError(pageErrorMessage(error, 'Unable to load context frame.'));
      if (detailOwnsPageStatus) {
        setPageErrors((errors) => ({ ...errors, context: error }));
        dispatch({ type: 'page/failed', view: 'context', message: pageErrorMessage(error, 'Unable to load context frame.') });
      }
    });
    return () => controller.abort();
  }, [client, contextDetailAttempt, contextSequence, hasAuditSelection, pageAttempts.context, state.activeView, state.selectedRunId]);

  useEffect(() => {
    const needsEvidence = state.activeView === 'evidence'
      || (!client.getEvidencePage && auditArtifactKey.length > 0);
    operationalOlderRequestRef.current.evidence?.controller.abort();
    operationalOlderRequestRef.current.evidence = null;
    if (!needsEvidence || !state.selectedRunId || (!client.getEvidencePage && !client.getEvidenceIndex)) {
      operationalRequestKeyRef.current.evidence = '';
      return;
    }
    const requestedRunId = state.selectedRunId;
    const filters = { ...state.pageFilters.evidence };
    const request: EvidencePageRequest = { filters };
    const requestKey = pageRequestKey(requestedRunId, 'evidence', { filters: { ...filters } });
    const isNewIdentity = operationalBaseRequestKeyRef.current.evidence !== requestKey;
    const showInitialLoading = isNewIdentity || (client.getEvidencePage ? evidencePageState.page === null : legacyEvidenceIndex === null);
    const controller = new AbortController();
    operationalBaseRequestKeyRef.current.evidence = requestKey;
    operationalRequestKeyRef.current.evidence = requestKey;
    if (client.getEvidencePage) {
      setEvidencePageState((current) => isNewIdentity
        ? { items: [], page: null, olderState: 'idle', olderError: null, failedCursor: null, requestKey }
        : { ...current, olderState: 'idle', olderError: null, failedCursor: null, requestKey });
    }
    if (isNewIdentity) setLegacyEvidenceIndex(null);
    setPageErrors((errors) => ({ ...errors, evidence: null }));
    if (showInitialLoading) dispatch({ type: 'page/requested', view: 'evidence' });
    const response = client.getEvidencePage
      ? client.getEvidencePage(requestedRunId, request, controller.signal)
      : client.getEvidenceIndex!(requestedRunId, controller.signal);
    void response.then((result) => {
      if (
        controller.signal.aborted
        || operationalRequestKeyRef.current.evidence !== requestKey
        || result.analysis_id !== requestedRunId
      ) return;
      if ('items' in result) {
        setLegacyEvidenceIndex(null);
        setEvidencePageState((current) => ({
          items: isNewIdentity ? result.items : prependOperationalPage(current.items, result.items),
          page: isNewIdentity ? result : current.page ?? result,
          olderState: 'idle', olderError: null, failedCursor: null, requestKey,
        }));
        if (showInitialLoading) dispatch({ type: 'page/loaded', view: 'evidence', page: pageMetadata(result) });
      } else {
        setLegacyEvidenceIndex(result);
        if (showInitialLoading) dispatch({ type: 'page/loaded', view: 'evidence', page: { firstSequence: null, lastSequence: null, hasOlder: false } });
      }
    }).catch((error: unknown) => {
      if (controller.signal.aborted || operationalRequestKeyRef.current.evidence !== requestKey) return;
      setPageErrors((errors) => ({ ...errors, evidence: error }));
      if (showInitialLoading) dispatch({ type: 'page/failed', view: 'evidence', message: pageErrorMessage(error, 'Unable to load evidence projection.') });
    });
    return () => controller.abort();
  }, [auditArtifactKey, client, pageAttempts.evidence, state.activeView, state.pageFilters.evidence, state.selectedRunId]);

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
  const loadOlderOperational = (view: 'agent' | 'context' | 'evidence', cursor: string) => {
    const runId = state.selectedRunId;
    if (!runId || !cursor) return;

    if (view === 'agent') {
      if (!client.getAgentPage || !agentPageState.page?.has_older || agentPageState.olderState === 'loading') return;
      const filters = { ...state.pageFilters.agent };
      const request: AgentPageRequest = { cursor, filters };
      const requestKey = pageRequestKey(runId, view, { cursor, filters: { ...filters } });
      const controller = new AbortController();
      const pending = { controller, requestKey };
      operationalOlderRequestRef.current.agent?.controller.abort();
      operationalOlderRequestRef.current.agent = pending;
      operationalRequestKeyRef.current.agent = requestKey;
      setAgentPageState((current) => ({ ...current, olderState: 'loading', olderError: null, failedCursor: null, requestKey }));
      setPageErrors((errors) => ({ ...errors, agent: null }));
      void client.getAgentPage(runId, request, controller.signal).then((page) => {
        if (
          controller.signal.aborted
          || operationalOlderRequestRef.current.agent !== pending
          || operationalRequestKeyRef.current.agent !== requestKey
          || page.analysis_id !== runId
        ) return;
        setAgentPageState((current) => ({
          items: prependOperationalPage(page.items, current.items), page,
          olderState: 'idle', olderError: null, failedCursor: null, requestKey,
        }));
        dispatch({ type: 'page/prepended', view, page: pageMetadata(page) });
      }).catch((error: unknown) => {
        if (controller.signal.aborted || operationalOlderRequestRef.current.agent !== pending) return;
        setAgentPageState((current) => ({
          ...current, olderState: 'failed', olderError: pageErrorMessage(error, 'Unable to load older agent trajectory.'),
          failedCursor: cursor, requestKey,
        }));
      }).finally(() => {
        if (operationalOlderRequestRef.current.agent === pending) operationalOlderRequestRef.current.agent = null;
      });
      return;
    }

    if (view === 'context') {
      if (!client.getContextPage || !contextPageState.page?.has_older || contextPageState.olderState === 'loading') return;
      const filters = { ...state.pageFilters.context };
      const request: ContextPageRequest = { cursor, filters };
      const requestKey = pageRequestKey(runId, view, { cursor, filters: { ...filters } });
      const controller = new AbortController();
      const pending = { controller, requestKey };
      operationalOlderRequestRef.current.context?.controller.abort();
      operationalOlderRequestRef.current.context = pending;
      operationalRequestKeyRef.current.context = requestKey;
      setContextPageState((current) => ({ ...current, olderState: 'loading', olderError: null, failedCursor: null, requestKey }));
      setPageErrors((errors) => ({ ...errors, context: null }));
      void client.getContextPage(runId, request, controller.signal).then((page) => {
        if (
          controller.signal.aborted
          || operationalOlderRequestRef.current.context !== pending
          || operationalRequestKeyRef.current.context !== requestKey
          || page.analysis_id !== runId
        ) return;
        setContextPageState((current) => ({
          items: prependOperationalPage(page.items, current.items), page,
          olderState: 'idle', olderError: null, failedCursor: null, requestKey,
        }));
        dispatch({ type: 'page/prepended', view, page: pageMetadata(page) });
      }).catch((error: unknown) => {
        if (controller.signal.aborted || operationalOlderRequestRef.current.context !== pending) return;
        setContextPageState((current) => ({
          ...current, olderState: 'failed', olderError: pageErrorMessage(error, 'Unable to load older context trajectory.'),
          failedCursor: cursor, requestKey,
        }));
      }).finally(() => {
        if (operationalOlderRequestRef.current.context === pending) operationalOlderRequestRef.current.context = null;
      });
      return;
    }

    if (!client.getEvidencePage || !evidencePageState.page?.has_older || evidencePageState.olderState === 'loading') return;
    const filters = { ...state.pageFilters.evidence };
    const request: EvidencePageRequest = { cursor, filters };
    const requestKey = pageRequestKey(runId, view, { cursor, filters: { ...filters } });
    const controller = new AbortController();
    const pending = { controller, requestKey };
    operationalOlderRequestRef.current.evidence?.controller.abort();
    operationalOlderRequestRef.current.evidence = pending;
    operationalRequestKeyRef.current.evidence = requestKey;
    setEvidencePageState((current) => ({ ...current, olderState: 'loading', olderError: null, failedCursor: null, requestKey }));
    setPageErrors((errors) => ({ ...errors, evidence: null }));
    void client.getEvidencePage(runId, request, controller.signal).then((page) => {
      if (
        controller.signal.aborted
        || operationalOlderRequestRef.current.evidence !== pending
        || operationalRequestKeyRef.current.evidence !== requestKey
        || page.analysis_id !== runId
      ) return;
      setEvidencePageState((current) => ({
        items: prependOperationalPage(page.items, current.items), page,
        olderState: 'idle', olderError: null, failedCursor: null, requestKey,
      }));
      dispatch({ type: 'page/prepended', view, page: pageMetadata(page) });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || operationalOlderRequestRef.current.evidence !== pending) return;
      setEvidencePageState((current) => ({
        ...current, olderState: 'failed', olderError: pageErrorMessage(error, 'Unable to load older evidence trajectory.'),
        failedCursor: cursor, requestKey,
      }));
    }).finally(() => {
      if (operationalOlderRequestRef.current.evidence === pending) operationalOlderRequestRef.current.evidence = null;
    });
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
  const activeOperationalPageState = state.activeView === 'evidence' ? evidencePageState : null;
  const operationalPaging = activeOperationalPageState ? <div className="operational-paging" aria-live="polite">
    {activeOperationalPageState.olderState === 'failed' ? <>
      <p role="alert">{activeOperationalPageState.olderError}</p>
      <button type="button" onClick={() => {
        if (activeOperationalPageState.failedCursor) loadOlderOperational(state.activeView as 'agent' | 'context' | 'evidence', activeOperationalPageState.failedCursor);
      }}>Retry older {state.activeView} history</button>
    </> : activeOperationalPageState.page?.has_older && activeOperationalPageState.page.older_cursor ? <button
      type="button"
      disabled={activeOperationalPageState.olderState === 'loading'}
      onClick={() => loadOlderOperational(state.activeView as 'agent' | 'context' | 'evidence', activeOperationalPageState.page!.older_cursor!)}
    >{activeOperationalPageState.olderState === 'loading' ? `Loading older ${state.activeView} history` : `Load older ${state.activeView} history`}</button> : null}
  </div> : null;
  const content = <section id={`workbench-panel-${state.activeView}`} role="tabpanel" aria-label={`${state.activeView} trajectory`} aria-busy={viewState === 'loading'}>
    {selectedRun?.status === 'partial' ? <AsyncState state="partial" diagnostic={selectedRun.diagnostic} /> : null}
    <AsyncState state={viewState} diagnostic={state.pageError[state.activeView]} onRetry={retryActivePage}>
    <>
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
      : state.activeView === 'agent' ? <AgentView
        rows={agentRows}
        filters={state.pageFilters.agent}
        onFiltersChange={(filters) => dispatch({ type: 'page/filtersChanged', view: 'agent', filters })}
        hasOlder={agentPageState.page?.has_older ?? false}
        olderState={agentPageState.olderState}
        olderError={agentPageState.olderError}
        onLoadOlder={() => {
          const cursor = agentPageState.page?.older_cursor;
          if (cursor) loadOlderOperational('agent', cursor);
        }}
        onRetryOlder={() => {
          if (agentPageState.failedCursor) loadOlderOperational('agent', agentPageState.failedCursor);
        }}
        selectedNodeId={state.selectedNodeId}
        businessSequences={problems.flatMap((problem) => [problem.source_sequence, ...problem.nodes.map((node) => node.source_sequence)])}
        onSelectNode={(nodeId) => dispatch({ type: 'node/selected', nodeId })}
        onSelectSequence={selectSequence}
      />
        : state.activeView === 'context' ? <ContextView
          summaries={contextSummaries}
          filters={state.pageFilters.context}
          onFiltersChange={(filters) => dispatch({ type: 'page/filtersChanged', view: 'context', filters })}
          hasOlder={contextPageState.page?.has_older ?? false}
          olderState={contextPageState.olderState}
          olderError={contextPageState.olderError}
          onLoadOlder={() => {
            const cursor = contextPageState.page?.older_cursor;
            if (cursor) loadOlderOperational('context', cursor);
          }}
          onRetryOlder={() => {
            if (contextPageState.failedCursor) loadOlderOperational('context', contextPageState.failedCursor);
          }}
          selectedSequence={contextSequence}
          frame={contextFrame}
          detailState={contextDetailState}
          detailError={contextDetailError}
          onRetryDetail={() => setContextDetailAttempt((attempt) => attempt + 1)}
          onSelectSequence={(sequence) => { setContextSequence(sequence); dispatch({ type: 'node/selected', nodeId: `context:${sequence}` }); }}
          artifactUrl={artifactUrl}
          comparisonIdentity={pageRequestKey(state.selectedRunId ?? '', 'context', { filters: { ...state.pageFilters.context } })}
        />
          : <EvidenceView index={evidenceIndex} selectedRefs={auditSelection?.artifactRefs ?? (state.selectedNodeId ? [state.selectedNodeId] : [])} onSelectRef={(ref) => dispatch({ type: 'node/selected', nodeId: ref })} artifactUrl={artifactUrl} />}
    {operationalPaging}
    </>
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
