import { useEffect, useMemo, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import type {
  ContextFrame,
  ContextFrameSummary,
  ContextPageFilters,
  JsonValue,
} from '../api/types';
import { compareContextStates, type ContextComparison } from '../context/compare';

interface ContextViewProps {
  summaries?: ContextFrameSummary[];
  filters?: ContextPageFilters;
  onFiltersChange?: (filters: ContextPageFilters) => void;
  hasOlder?: boolean;
  olderState?: 'idle' | 'loading' | 'failed';
  olderError?: string | null;
  onLoadOlder?: () => void;
  onRetryOlder?: () => void;
  selectedSequence?: number | null;
  frame: ContextFrame | null;
  detailState?: 'idle' | 'loading' | 'ready' | 'failed';
  detailError?: string | null;
  onRetryDetail?: () => void;
  onSelectSequence: (sequence: number) => void;
  artifactUrl: (ref: string) => string;
  comparisonIdentity?: string;
}

const labels = ['Before', 'Delta', 'After'] as const;
type StateLabel = typeof labels[number];

function displayPrimitive(value: JsonValue): string {
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function StructuredNode({ name, value, depth }: { name: string; value: JsonValue; depth: number }) {
  if (typeof value !== 'object' || value === null) {
    return <div role="treeitem" aria-level={depth} className="context-state-leaf"><span>{name}</span><code>{displayPrimitive(value)}</code></div>;
  }
  const entries = Array.isArray(value)
    ? value.map((entry, index) => [`[${index}]`, entry] as const)
    : Object.entries(value);
  return <details role="treeitem" aria-level={depth} className="context-state-branch" open={depth === 1}>
    <summary>{name}<small>{Array.isArray(value) ? `${value.length} items` : `${entries.length} keys`}</small></summary>
    <div role="group">
      {entries.length > 0
        ? entries.map(([key, entry]) => <StructuredNode key={key} name={key} value={entry} depth={depth + 1} />)
        : <span className="context-empty-value">Empty {Array.isArray(value) ? 'array' : 'object'}</span>}
    </div>
  </details>;
}

function StructuredState({ label, value }: { label: StateLabel; value: JsonValue }) {
  const rootName = Array.isArray(value) ? 'Recorded array' : 'Recorded state';
  return <>
    <div role="tree" aria-label={`${label} recorded context state`} className="context-state-tree">
      <StructuredNode name={rootName} value={value} depth={1} />
    </div>
    <RawDisclosure value={value} />
  </>;
}

function RawDisclosure({ value }: { value: JsonValue }) {
  const [open, setOpen] = useState(false);
  return <details className="context-raw" open={open}>
    <summary onClick={(event) => { event.preventDefault(); setOpen((current) => !current); }}>Raw recorded JSON</summary>
    {open ? <pre className="json-document">{JSON.stringify(value, null, 2)}</pre> : null}
  </details>;
}

function ComparisonList({ comparison }: { comparison: ContextComparison }) {
  const groups = [
    ['Added', comparison.added],
    ['Removed', comparison.removed],
    ['Changed', comparison.changed],
  ] as const;
  return <div className="context-comparison-groups">
    {groups.map(([label, paths]) => <section key={label} aria-label={`${label} context keys`}>
      <h3>{label} <small>{paths.length}</small></h3>
      {paths.length > 0 ? <ul>{paths.map((path) => <li key={path}><code>{path}</code></li>)}</ul> : <p>None</p>}
    </section>)}
  </div>;
}

function ContextPagination({
  hasOlder, state, error, onLoad, onRetry,
}: {
  hasOlder: boolean;
  state: ContextViewProps['olderState'];
  error: string | null;
  onLoad: () => void;
  onRetry: () => void;
}) {
  if (state === 'failed') return <div className="context-load-older context-older-error"><span role="alert">{error}</span><button type="button" onClick={onRetry}>Retry older context history</button></div>;
  if (!hasOlder) return null;
  return <button type="button" className="context-load-older" disabled={state === 'loading'} onClick={onLoad}>
    {state === 'loading' ? 'Loading older context history' : 'Load older context history'}
  </button>;
}

function optionalNumber(value: string): number | null {
  if (value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ContextView({
  summaries = [],
  filters = {},
  onFiltersChange = () => undefined,
  hasOlder = false,
  olderState = 'idle',
  olderError = null,
  onLoadOlder = () => undefined,
  onRetryOlder = () => undefined,
  selectedSequence,
  frame,
  detailState,
  detailError = null,
  onRetryDetail = () => undefined,
  onSelectSequence,
  artifactUrl,
  comparisonIdentity = 'legacy-detail',
}: ContextViewProps) {
  const [active, setActive] = useState<StateLabel>('Before');
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const [pinnedA, setPinnedA] = useState<ContextFrame | null>(null);
  const [pinnedB, setPinnedB] = useState<ContextFrame | null>(null);
  const loadedSequences = useMemo(() => [...new Set(summaries.map((summary) => summary.source_sequence))].sort((a, b) => a - b), [summaries]);
  const effectiveSelectedSequence = selectedSequence ?? frame?.source_sequence ?? null;
  const selectedIndex = effectiveSelectedSequence === null ? -1 : loadedSequences.indexOf(effectiveSelectedSequence);
  const effectiveDetailState = detailState ?? (frame ? 'ready' : 'idle');
  const virtualizer = useVirtualizer({
    count: summaries.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => 48,
    getItemKey: (index) => summaries[index]?.id ?? index,
    overscan: 8,
    useFlushSync: false,
    initialRect: { width: 420, height: 480 },
  });
  const baseVirtualRows = virtualizer.getVirtualItems();
  const virtualRows = baseVirtualRows.length > 0
    ? baseVirtualRows
    : summaries.slice(0, 16).map((summary, index) => ({ index, key: summary.id, start: index * 48 }));
  const comparison = useMemo(() => pinnedA && pinnedB
    ? compareContextStates(pinnedA.after_state, pinnedB.after_state)
    : null, [pinnedA, pinnedB]);

  useEffect(() => {
    setPinnedA(null);
    setPinnedB(null);
  }, [comparisonIdentity]);

  const updateFilter = <K extends keyof ContextPageFilters>(name: K, value: ContextPageFilters[K] | null) => {
    const next = { ...filters };
    if (value === null) delete next[name];
    else next[name] = value;
    onFiltersChange(next);
  };
  const stateValue = frame ? { Before: frame.before_state, Delta: frame.delta, After: frame.after_state }[active] : null;

  return <section className="context-view" aria-label="Context time travel">
    <header className="context-view-header">
      <div><h1>Context replay</h1><p>Browse bounded frame summaries, then fetch an exact recorded state for inspection.</p></div>
      <div className="context-controls">
        <label>From sequence<input aria-label="Context from sequence" type="number" min="1" value={filters.from_sequence ?? ''} onChange={(event) => updateFilter('from_sequence', optionalNumber(event.target.value))} /></label>
        <label>To sequence<input aria-label="Context to sequence" type="number" min="1" value={filters.to_sequence ?? ''} onChange={(event) => updateFilter('to_sequence', optionalNumber(event.target.value))} /></label>
        <label>From revision<input aria-label="Context from revision" type="number" min="0" value={filters.from_revision ?? ''} onChange={(event) => updateFilter('from_revision', optionalNumber(event.target.value))} /></label>
        <label>To revision<input aria-label="Context to revision" type="number" min="0" value={filters.to_revision ?? ''} onChange={(event) => updateFilter('to_revision', optionalNumber(event.target.value))} /></label>
        <label>Changed<select aria-label="Context changed state" value={filters.changed === undefined || filters.changed === null ? '' : String(filters.changed)} onChange={(event) => updateFilter('changed', event.target.value === '' ? null : event.target.value === 'true')}><option value="">All frames</option><option value="true">Changed</option><option value="false">Unchanged</option></select></label>
        <label>Request input<select aria-label="Context request input" value={filters.request_input === undefined || filters.request_input === null ? '' : String(filters.request_input)} onChange={(event) => updateFilter('request_input', event.target.value === '' ? null : event.target.value === 'true')}><option value="">All frames</option><option value="true">Available</option><option value="false">Unavailable</option></select></label>
      </div>
    </header>

    <div className="context-replay-layout">
      <section className="context-timeline" aria-label="Context frame timeline">
        <p className="context-filter-summary" aria-live="polite">{summaries.length} loaded frames</p>
        <div ref={setScrollElement} className="context-summary-scroll">
          <ContextPagination hasOlder={hasOlder} state={olderState} error={olderError} onLoad={onLoadOlder} onRetry={onRetryOlder} />
          {summaries.length === 0 ? <p className="unavailable">No context frames match the current filters.</p> : <div role="list" aria-label="Loaded context frames" className="context-summary-list" style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualRows.map((virtualRow) => {
              const summary = summaries[virtualRow.index];
              if (!summary) return null;
              return <div
                role="listitem"
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{ position: 'absolute', width: '100%', transform: `translateY(${virtualRow.start}px)` }}
              >
                <button
                  type="button"
                  aria-current={effectiveSelectedSequence === summary.source_sequence ? 'true' : undefined}
                  aria-label={`Sequence ${summary.source_sequence}, ${summary.event_kind}, revisions ${summary.before_revision} to ${summary.after_revision}`}
                  className="context-summary-row"
                  onClick={() => onSelectSequence(summary.source_sequence)}
                >
                  <strong>Sequence {summary.source_sequence}</strong><span>{summary.event_kind}</span>
                  <small>r{summary.before_revision} → r{summary.after_revision} · {summary.changed ? 'changed' : 'unchanged'} · request {summary.request_input_available ? 'available' : 'unavailable'}</small>
                  {!summary.request_input_available && summary.request_input_unavailable_reason
                    ? <small className="unavailable">{summary.request_input_unavailable_reason}</small>
                    : null}
                </button>
              </div>;
            })}
          </div>}
        </div>
      </section>

      <section className="context-detail" aria-label="Selected context frame">
        <div className="context-detail-navigation">
          <button type="button" aria-label="Previous loaded frame" disabled={selectedIndex <= 0} onClick={() => onSelectSequence(loadedSequences[selectedIndex - 1])}>Previous</button>
          <button type="button" aria-label="Next loaded frame" disabled={selectedIndex < 0 || selectedIndex >= loadedSequences.length - 1} onClick={() => onSelectSequence(loadedSequences[selectedIndex + 1])}>Next</button>
        </div>
        {effectiveDetailState === 'loading' ? <p role="status">Loading exact context frame {effectiveSelectedSequence}…</p>
          : effectiveDetailState === 'failed' ? <div className="context-detail-error"><p role="alert">{detailError}</p><button type="button" onClick={onRetryDetail}>Retry exact context frame</button></div>
            : !frame ? <p className="unavailable">Select a loaded frame to fetch its exact recorded detail.</p>
              : <>
                <header><h2>Authoritative state at sequence {frame.source_sequence}</h2><p>Revisions {frame.before_revision} → {frame.after_revision}.</p></header>
                {summaries.length === 0 ? <label className="sequence-scrubber">Event sequence <input type="range" min={1} max={Math.max(1, frame.max_sequence)} value={frame.source_sequence} onChange={(event) => onSelectSequence(Number(event.target.value))} /><output>{frame.source_sequence}</output></label> : null}
                <div className="context-pin-controls">
                  <button type="button" onClick={() => setPinnedA(frame)}>Pin sequence {frame.source_sequence} as frame A</button>
                  <button type="button" onClick={() => setPinnedB(frame)}>Pin sequence {frame.source_sequence} as frame B</button>
                </div>
                <div role="tablist" aria-label="Context state">{labels.map((label) => <button key={label} type="button" role="tab" aria-selected={active === label} onClick={() => setActive(label)}>{label}</button>)}</div>
                <section role="tabpanel" aria-label={`${active} context state`} className="context-panel">
                  {stateValue === null ? null : <StructuredState key={`${frame.id}:${active}`} label={active} value={stateValue} />}
                </section>
                <section className="request-input" aria-label="Model-visible request input"><h2>Model-visible request input</h2>{frame.request_input_available && frame.request_artifact_ref ? <a href={artifactUrl(frame.request_artifact_ref)} download>{frame.request_artifact_ref}</a> : <p className="unavailable">{frame.request_input_unavailable_reason || frame.unavailable_reason || 'No following model request'}</p>}</section>
              </>}
      </section>
    </div>

    <section className="context-comparison" aria-label="Pinned frame comparison">
      <header><h2>Authoritative frame comparison</h2><p>{pinnedA ? `A · sequence ${pinnedA.source_sequence}` : 'Pin frame A'} · {pinnedB ? `B · sequence ${pinnedB.source_sequence}` : 'Pin frame B'}</p></header>
      {comparison ? <ComparisonList comparison={comparison} /> : <p className="unavailable">Pin two fetched frames to compare their recorded after states.</p>}
    </section>
  </section>;
}
