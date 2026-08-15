import type {
  AgentEventRow, AgentPageRequest, ApiErrorResponse, BusinessCausalRow, ContextFrame, ContextFrameSummary,
  ContextPageRequest, EvidenceIndex, EvidencePageRequest, EvidenceRecord, ExecutionSlice, ProjectionPage,
  RunListResponse, RunSummary,
} from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    const fallback = `Trajectory API request failed with status ${response.status}`;
    try {
      const body = await response.json() as ApiErrorResponse;
      return new ApiError(response.status, body.code, body.message);
    } catch {
      return new ApiError(response.status, 'http_error', fallback);
    }
  }
}

export class TrajectoryApiClient {
  constructor(private readonly fetcher: typeof fetch = (...args) => globalThis.fetch(...args)) {}

  private async get<T>(path: string, signal?: AbortSignal): Promise<T> {
    if (!path.startsWith('/api/')) throw new Error('trajectory API path must be same-origin');
    const response = await this.fetcher(path, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      signal,
    });
    if (!response.ok) throw await ApiError.fromResponse(response);
    return await response.json() as T;
  }

  listRuns(signal?: AbortSignal) { return this.get<RunListResponse>('/api/runs', signal); }
  getRun(id: string, signal?: AbortSignal) {
    return this.get<RunSummary>(`/api/runs/${encodeURIComponent(id)}`, signal);
  }
  getBusinessPage(id: string, cursor?: string, signal?: AbortSignal) {
    return this.get<ProjectionPage<BusinessCausalRow>>(this.pagePath(id, 'business', cursor), signal);
  }
  getAgentPage(id: string, request: AgentPageRequest = { filters: {} }, signal?: AbortSignal) {
    return this.get<ProjectionPage<AgentEventRow>>(this.operationalPagePath(id, 'agent', request), signal);
  }
  getContextPage(id: string, request: ContextPageRequest = { filters: {} }, signal?: AbortSignal) {
    return this.get<ProjectionPage<ContextFrameSummary>>(this.operationalPagePath(id, 'context', request), signal);
  }
  getEvidencePage(id: string, request: EvidencePageRequest = { filters: {} }, signal?: AbortSignal) {
    return this.get<ProjectionPage<EvidenceRecord>>(this.operationalPagePath(id, 'evidence', request), signal);
  }
  getContextFrame(id: string, atSequence: number, signal?: AbortSignal) {
    return this.get<ContextFrame>(`/api/runs/${encodeURIComponent(id)}/context?at_sequence=${atSequence}`, signal);
  }
  getExecutionSlice(id: string, atSequence: number, signal?: AbortSignal) {
    return this.get<ExecutionSlice>(`/api/runs/${encodeURIComponent(id)}/execution?at_sequence=${atSequence}`, signal);
  }
  getEvidenceIndex(id: string, signal?: AbortSignal) {
    return this.get<EvidenceIndex>(`/api/runs/${encodeURIComponent(id)}/evidence`, signal);
  }
  artifactUrl(id: string, ref: string) {
    return `/api/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(ref)}`;
  }

  private pagePath(id: string, view: 'business' | 'agent', cursor?: string) {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
    return `/api/runs/${encodeURIComponent(id)}/${view}${query}`;
  }

  private operationalPagePath(
    id: string,
    view: 'agent' | 'context' | 'evidence',
    request: { cursor?: string; filters: object },
  ) {
    const query = new URLSearchParams();
    if (request.cursor) query.set('cursor', request.cursor);
    for (const [name, value] of Object.entries(request.filters).sort(([left], [right]) => left.localeCompare(right))) {
      if (value !== null && value !== undefined) query.set(name, String(value));
    }
    const encoded = query.toString();
    return `/api/runs/${encodeURIComponent(id)}/${view}${encoded ? `?${encoded}` : ''}`;
  }
}
