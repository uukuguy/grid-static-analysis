import type {
  AgentTurn, ApiErrorResponse, BusinessProblem, ContextFrame, EvidenceIndex, ProjectionPage, RunListResponse, RunSummary,
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
  constructor(private readonly fetcher: typeof fetch = fetch) {}

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
    return this.get<ProjectionPage<BusinessProblem>>(this.pagePath(id, 'business', cursor), signal);
  }
  getAgentPage(id: string, cursor?: string, signal?: AbortSignal) {
    return this.get<ProjectionPage<AgentTurn>>(this.pagePath(id, 'agent', cursor), signal);
  }
  getContextFrame(id: string, atSequence: number, signal?: AbortSignal) {
    return this.get<ContextFrame>(`/api/runs/${encodeURIComponent(id)}/context?at_sequence=${atSequence}`, signal);
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
}
