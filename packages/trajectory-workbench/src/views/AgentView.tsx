import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import type {
  AgentEventKind,
  AgentEventRow,
  AgentPageFilters,
  LifecycleStatus,
} from '../api/types';

interface AgentViewProps {
  rows: AgentEventRow[];
  filters: AgentPageFilters;
  onFiltersChange: (filters: AgentPageFilters) => void;
  hasOlder: boolean;
  olderState: 'idle' | 'loading' | 'failed';
  olderError: string | null;
  onLoadOlder: () => void;
  onRetryOlder: () => void;
  selectedNodeId: string | null;
  businessSequences?: readonly number[];
  onSelectNode: (id: string) => void;
  onSelectSequence: (sequence: number) => void;
}

interface VisibleAgentRow {
  row: AgentEventRow;
  parentPresent: boolean;
}

const kinds: AgentEventKind[] = ['turn', 'step', 'request', 'retry', 'response', 'tool'];
const statuses: LifecycleStatus[] = ['running', 'completed', 'failed', 'interrupted', 'unavailable'];
const sequenceNavigableKinds = new Set<AgentEventKind>(['request', 'response', 'tool']);

/** Build only relationships proven by parent IDs in the currently loaded page set. */
function visibleHierarchy(rows: AgentEventRow[], collapsed: ReadonlySet<string>): VisibleAgentRow[] {
  const byId = new Map(rows.map((row) => [row.id, row]));
  const children = new Map<string, AgentEventRow[]>();
  for (const row of rows) {
    if (!row.parent_id || !byId.has(row.parent_id)) continue;
    const siblings = children.get(row.parent_id) ?? [];
    siblings.push(row);
    children.set(row.parent_id, siblings);
  }
  const result: VisibleAgentRow[] = [];
  const visited = new Set<string>();
  const visit = (row: AgentEventRow) => {
    if (visited.has(row.id)) return;
    visited.add(row.id);
    result.push({ row, parentPresent: row.parent_id === null || byId.has(row.parent_id) });
    if (collapsed.has(row.id)) return;
    for (const child of children.get(row.id) ?? []) visit(child);
  };
  for (const row of rows) {
    if (row.parent_id === null || !byId.has(row.parent_id)) visit(row);
  }
  // A malformed cycle cannot invent a hierarchy; preserve the public rows as truncated roots.
  for (const row of rows) visit(row);
  return result;
}

export function AgentView({
  rows,
  filters,
  onFiltersChange,
  hasOlder,
  olderState,
  olderError,
  onLoadOlder,
  onRetryOlder,
  selectedNodeId,
  businessSequences = [],
  onSelectNode,
  onSelectSequence,
}: AgentViewProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [activeId, setActiveId] = useState<string | null>(() => rows[0]?.id ?? null);
  const [activatedId, setActivatedId] = useState<string | null>(null);
  const visible = useMemo(() => visibleHierarchy(rows, collapsed), [collapsed, rows]);
  const byId = useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows]);
  const children = useMemo(() => {
    const result = new Map<string, AgentEventRow[]>();
    for (const row of rows) {
      if (!row.parent_id || !byId.has(row.parent_id)) continue;
      result.set(row.parent_id, [...(result.get(row.parent_id) ?? []), row]);
    }
    return result;
  }, [byId, rows]);
  const parentRef = useRef<HTMLDivElement | null>(null);
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingFocusId = useRef<string | null>(null);
  const virtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => scrollElement,
    estimateSize: (index) => visible[index]?.parentPresent === false ? 70 : 52,
    getItemKey: (index) => visible[index]?.row.id ?? index,
    overscan: 8,
    useFlushSync: false,
    initialRect: { width: 900, height: 700 },
  });

  useEffect(() => {
    setActiveId((current) => current && visible.some(({ row }) => row.id === current)
      ? current
      : visible[0]?.row.id ?? null);
  }, [visible]);

  const baseVirtualRows = virtualizer.getVirtualItems();
  const virtualRows = baseVirtualRows.length > 0
    ? baseVirtualRows
    : visible.slice(0, 16).map((_, index) => ({
      index,
      key: visible[index].row.id,
      start: index * 52,
    }));

  useEffect(() => {
    const id = pendingFocusId.current;
    if (!id) return;
    const element = rowRefs.current.get(id);
    if (!element) return;
    element.focus({ preventScroll: true });
    pendingFocusId.current = null;
  }, [virtualRows]);

  const updateFilter = <K extends keyof AgentPageFilters>(name: K, value: AgentPageFilters[K] | null) => {
    const next = { ...filters };
    if (value === null || value === '') delete next[name];
    else next[name] = value;
    onFiltersChange(next);
  };
  const focusAt = (index: number) => {
    const item = visible[index];
    if (!item) return;
    setActiveId(item.row.id);
    const mounted = rowRefs.current.get(item.row.id);
    if (mounted) mounted.focus();
    else {
      pendingFocusId.current = item.row.id;
      virtualizer.scrollToIndex(index, { align: 'auto' });
    }
  };
  const toggle = (id: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const activate = (row: AgentEventRow) => {
    setActivatedId(row.id);
    onSelectNode(row.id);
  };
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>, row: AgentEventRow) => {
    const index = visible.findIndex((item) => item.row.id === row.id);
    const childRows = children.get(row.id) ?? [];
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusAt(Math.min(index + 1, visible.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusAt(Math.max(index - 1, 0));
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusAt(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusAt(visible.length - 1);
    } else if (event.key === 'ArrowRight' && childRows.length > 0) {
      event.preventDefault();
      if (collapsed.has(row.id)) toggle(row.id);
      else focusAt(index + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      if (childRows.length > 0 && !collapsed.has(row.id)) toggle(row.id);
      else if (row.parent_id && byId.has(row.parent_id)) {
        const parentIndex = visible.findIndex((item) => item.row.id === row.parent_id);
        focusAt(parentIndex);
      }
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activate(row);
    }
  };
  const activated = activatedId ? byId.get(activatedId) ?? null : null;
  const hasBusinessRelation = activated
    ? businessSequences.includes(activated.source_sequence)
    : false;

  return <section className="agent-view" aria-label="Agent trajectory view">
    <header className="agent-view-header">
      <div><h1>Agent execution</h1><p>Bounded public request, response, retry, and tool lifecycle facts.</p></div>
      <div className="agent-controls">
        <label>Turn ID<input aria-label="Agent turn ID" value={filters.turn_id ?? ''} onChange={(event) => updateFilter('turn_id', event.target.value)} /></label>
        <label>Kind<select aria-label="Agent event kind" value={filters.kind ?? ''} onChange={(event) => updateFilter('kind', event.target.value ? event.target.value as AgentEventKind : null)}><option value="">All kinds</option>{kinds.map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select></label>
        <label>Status<select aria-label="Agent lifecycle status" value={filters.status ?? ''} onChange={(event) => updateFilter('status', event.target.value ? event.target.value as LifecycleStatus : null)}><option value="">All states</option>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
        <label>Capability<input aria-label="Agent capability" value={filters.capability ?? ''} onChange={(event) => updateFilter('capability', event.target.value)} /></label>
        <label>Query<input aria-label="Search agent events" value={filters.q ?? ''} onChange={(event) => updateFilter('q', event.target.value)} /></label>
      </div>
      <div className="agent-hierarchy-controls">
        <button type="button" onClick={() => setCollapsed(new Set())}>Expand all</button>
        <button type="button" onClick={() => setCollapsed(new Set(children.keys()))}>Collapse all</button>
      </div>
    </header>
    <p className="agent-filter-summary" aria-live="polite">{rows.length} loaded events{rows.length > 0 ? ` · sequences ${Math.min(...rows.map((row) => row.source_sequence))}–${Math.max(...rows.map((row) => row.source_sequence))}` : ''}</p>
    {activated && sequenceNavigableKinds.has(activated.kind)
      ? hasBusinessRelation
        ? <p className="agent-relation-status" role="status">Recorded Business relationship at sequence {activated.source_sequence}. <button type="button" onClick={() => onSelectSequence(activated.source_sequence)}>Go to recorded Business sequence {activated.source_sequence}</button></p>
        : <p className="agent-relation-status" role="status">No recorded Business relationship exists at sequence {activated.source_sequence}.</p>
      : null}
    <div ref={(element) => { parentRef.current = element; setScrollElement(element); }} className="agent-virtual-scroll">
      <AgentPagination hasOlder={hasOlder} state={olderState} error={olderError} onLoad={onLoadOlder} onRetry={onRetryOlder} />
      {rows.length === 0 ? <p className="unavailable">No agent execution events match the current filters.</p> : <div role="treegrid" aria-label="Agent execution events" aria-rowcount={visible.length + 1} aria-busy={olderState === 'loading' ? 'true' : 'false'} className="agent-treegrid">
        <div role="row" className="agent-treegrid-head"><span role="columnheader">Event</span><span role="columnheader">Lifecycle</span><span role="columnheader">Sequence</span></div>
        <div role="rowgroup" style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualRows.map((virtualRow) => {
            const item = visible[virtualRow.index];
            if (!item) return null;
            const row = item.row;
            const hasChildren = (children.get(row.id)?.length ?? 0) > 0;
            const isExpanded = hasChildren && !collapsed.has(row.id);
            return <div
              key={virtualRow.key}
              ref={(element) => {
                if (element) {
                  rowRefs.current.set(row.id, element);
                  virtualizer.measureElement(element);
                } else rowRefs.current.delete(row.id);
              }}
              data-index={virtualRow.index}
              data-testid={`agent-event-${row.id}`}
              role="row"
              aria-level={row.level}
              aria-expanded={hasChildren ? isExpanded : undefined}
              aria-selected={selectedNodeId === row.id}
              aria-rowindex={virtualRow.index + 2}
              tabIndex={activeId === row.id ? 0 : -1}
              className="agent-event-row"
              style={{ position: 'absolute', width: '100%', transform: `translateY(${virtualRow.start}px)`, paddingInlineStart: `calc(${Math.max(row.level - 1, 0)} * 18px)` }}
              onFocus={() => setActiveId(row.id)}
              onClick={() => activate(row)}
              onKeyDown={(event) => handleKeyDown(event, row)}
            >
              <span role="gridcell" className="agent-event-title">
                {hasChildren ? <button type="button" tabIndex={-1} className="tree-toggle" aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${row.title}`} onClick={(event) => { event.stopPropagation(); toggle(row.id); }}>{isExpanded ? '▾' : '▸'}</button> : <span className="tree-spacer" aria-hidden="true" />}
                <span><strong>{row.title}</strong>{!sequenceNavigableKinds.has(row.kind) ? <small>{row.kind} · {row.turn_id} · {row.source}</small> : null}{row.kind === 'retry' && row.detail ? <small>{row.detail}</small> : null}{!item.parentPresent && row.parent_id ? <small className="truncated-parent">Parent {row.parent_id} is outside loaded history.</small> : null}</span>
              </span>
              <span role="gridcell" className={`agent-event-status status-${row.status}`}>{row.status}</span>
              <span role="gridcell" className="agent-event-sequence">{row.kind === 'tool' && row.start_sequence !== null
                ? <>Lifecycle {row.start_sequence}{row.end_sequence === null ? ' · still open' : `–${row.end_sequence}`} · relation sequence {row.source_sequence}</>
                : <>Sequence {row.source_sequence}</>}</span>
            </div>;
          })}
        </div>
      </div>}
    </div>
  </section>;
}

function AgentPagination({
  hasOlder,
  state,
  error,
  onLoad,
  onRetry,
}: {
  hasOlder: boolean;
  state: 'idle' | 'loading' | 'failed';
  error: string | null;
  onLoad: () => void;
  onRetry: () => void;
}) {
  if (state === 'failed') return <div className="agent-load-older older-history-error" role="alert"><span>{error ?? 'Unable to load older agent history.'}</span><button type="button" onClick={onRetry}>Retry older agent history</button></div>;
  if (state === 'loading') return <button type="button" className="agent-load-older" disabled>Loading older agent history</button>;
  if (hasOlder) return <button type="button" className="agent-load-older" onClick={onLoad}>Load older agent history</button>;
  return null;
}
