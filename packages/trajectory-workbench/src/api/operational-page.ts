import type { ProjectionPage } from './types';
import type { WorkbenchView } from '../state/workbench';

export interface PageRequest {
  cursor?: string;
  filters: Record<string, string | number | boolean | null>;
}

export interface OperationalPageState<T> {
  items: T[];
  page: ProjectionPage<T> | null;
  olderState: 'idle' | 'loading' | 'failed';
  olderError: string | null;
  failedCursor: string | null;
  requestKey: string;
}

export function prependOperationalPage<T extends { id: string }>(older: T[], current: T[]): T[] {
  const order: string[] = [];
  const items = new Map<string, T>();
  for (const item of [...older, ...current]) {
    if (!items.has(item.id)) order.push(item.id);
    items.set(item.id, item);
  }
  return order.map((id) => items.get(id)!);
}

export function pageRequestKey(runId: string, view: WorkbenchView, request: PageRequest): string {
  const filters = Object.entries(request.filters)
    .filter(([, value]) => value !== null)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify([runId, view, request.cursor ?? null, filters]);
}
