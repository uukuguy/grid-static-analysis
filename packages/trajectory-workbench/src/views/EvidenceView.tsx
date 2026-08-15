import { useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import type { EvidencePageFilters, EvidenceRecord, NodeSource } from '../api/types';
import { SourceBadge } from '../components/common/SourceBadge';
import { loadSafePreview, type ArtifactPreview } from '../evidence/preview';

interface EvidenceViewProps {
  rows: EvidenceRecord[];
  filters?: EvidencePageFilters;
  onFiltersChange?: (filters: EvidencePageFilters) => void;
  hasOlder?: boolean;
  olderState?: 'idle' | 'loading' | 'failed';
  olderError?: string | null;
  onLoadOlder?: () => void;
  onRetryOlder?: () => void;
  selectedRefs: string[];
  onSelectRef: (ref: string) => void;
  artifactUrl: (ref: string) => string;
  onSelectSequence: (sequence: number) => void;
  fetcher?: typeof fetch;
  previewIdentity?: string;
}

interface PreviewState {
  reference: string;
  state: 'loading' | 'ready' | 'failed';
  preview: ArtifactPreview | null;
  error: string | null;
}

function optionalNumber(value: string): number | null {
  if (value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function unavailableReason(record: EvidenceRecord): string {
  return record.unavailable_reason || 'Artifact verification is unavailable for this record.';
}

function EvidencePagination({
  hasOlder, state, error, onLoad, onRetry,
}: {
  hasOlder: boolean;
  state: EvidenceViewProps['olderState'];
  error: string | null;
  onLoad: () => void;
  onRetry: () => void;
}) {
  if (state === 'failed') return <div className="evidence-load-older evidence-older-error"><span role="alert">{error}</span><button type="button" onClick={onRetry}>Retry older evidence history</button></div>;
  if (!hasOlder) return null;
  return <button type="button" className="evidence-load-older" disabled={state === 'loading'} onClick={onLoad}>
    {state === 'loading' ? 'Loading older evidence history' : 'Load older evidence history'}
  </button>;
}

function EvidenceLineage({ record, onSelectSequence }: { record: EvidenceRecord; onSelectSequence: (sequence: number) => void }) {
  return <>
    <span className="evidence-lineage-group"><strong>Producer</strong>{record.producing_sequence === null
      ? <span>Unavailable</span>
      : <button type="button" onClick={() => onSelectSequence(record.producing_sequence!)} aria-label={`Producer sequence ${record.producing_sequence}`}>{record.producing_sequence}</button>}</span>
    <span className="evidence-lineage-group"><strong>Consumers</strong>{record.consuming_sequences.length === 0
      ? <span>None recorded</span>
      : record.consuming_sequences.map((sequence) => <button type="button" key={sequence} onClick={() => onSelectSequence(sequence)} aria-label={`Consumer sequence ${sequence}`}>{sequence}</button>)}</span>
  </>;
}

export function EvidenceView({
  rows,
  filters = {},
  onFiltersChange = () => undefined,
  hasOlder = false,
  olderState = 'idle',
  olderError = null,
  onLoadOlder = () => undefined,
  onRetryOlder = () => undefined,
  selectedRefs,
  onSelectRef,
  artifactUrl,
  onSelectSequence,
  fetcher = fetch,
  previewIdentity = 'evidence',
}: EvidenceViewProps) {
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const [previewState, setPreviewState] = useState<PreviewState | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const previewRequest = useRef(0);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => 82,
    getItemKey: (index) => rows[index]?.id ?? index,
    overscan: 8,
    useFlushSync: false,
    initialRect: { width: 820, height: 560 },
  });
  const baseVirtualRows = virtualizer.getVirtualItems();
  const virtualRows = baseVirtualRows.length > 0
    ? baseVirtualRows
    : rows.slice(0, 16).map((row, index) => ({ index, key: row.id, start: index * 82 }));
  const loadedRange = useMemo(() => {
    const sequences = rows.flatMap((record) => record.producing_sequence === null ? record.source_sequences : [record.producing_sequence]);
    return sequences.length === 0 ? null : [Math.min(...sequences), Math.max(...sequences)] as const;
  }, [rows]);

  useEffect(() => {
    previewRequest.current += 1;
    setPreviewState(null);
  }, [previewIdentity]);

  useEffect(() => {
    if (previewState && !rows.some((record) => record.reference === previewState.reference)) {
      previewRequest.current += 1;
      setPreviewState(null);
    }
  }, [previewState, rows]);

  const updateFilter = <K extends keyof EvidencePageFilters>(name: K, value: EvidencePageFilters[K] | null) => {
    const next = { ...filters };
    if (value === null || value === '') delete next[name];
    else next[name] = value;
    onFiltersChange(next);
  };

  const openPreview = async (record: EvidenceRecord) => {
    if (record.verification_status !== 'verified') return;
    const requestId = previewRequest.current + 1;
    previewRequest.current = requestId;
    setPreviewState({ reference: record.reference, state: 'loading', preview: null, error: null });
    try {
      const preview = await loadSafePreview(artifactUrl(record.reference), fetcher);
      if (previewRequest.current !== requestId) return;
      setPreviewState({ reference: record.reference, state: 'ready', preview, error: null });
    } catch (error: unknown) {
      if (previewRequest.current !== requestId) return;
      setPreviewState({
        reference: record.reference,
        state: 'failed',
        preview: null,
        error: error instanceof Error ? error.message : 'Artifact preview failed.',
      });
    }
  };

  const closePreview = () => {
    previewRequest.current += 1;
    setPreviewState(null);
  };

  const copyReference = async (reference: string) => {
    try {
      await navigator.clipboard.writeText(reference);
      setCopyStatus(`Copied ${reference}`);
    } catch {
      setCopyStatus(`Unable to copy ${reference}`);
    }
  };

  const sourceValue = filters.source ?? '';
  return <section className="evidence-view" aria-label="Evidence view">
    <header className="evidence-view-header">
      <div><h1>Evidence investigation</h1><p>Browse bounded registered artifact facts and open verified display-only previews.</p></div>
      <div className="evidence-controls">
        <label>Kind<input aria-label="Evidence kind" value={filters.kind ?? ''} onChange={(event) => updateFilter('kind', event.target.value)} /></label>
        <label>Source<select aria-label="Evidence source" value={sourceValue} onChange={(event) => updateFilter('source', event.target.value === '' ? null : event.target.value as NodeSource)}><option value="">All sources</option><option value="observed">Observed</option><option value="derived">Derived</option><option value="agent-declared">Agent-declared</option></select></label>
        <label>Verification<select aria-label="Evidence verification" value={filters.verification_status ?? ''} onChange={(event) => updateFilter('verification_status', event.target.value === '' ? null : event.target.value as 'verified' | 'unavailable')}><option value="">All records</option><option value="verified">Verified</option><option value="unavailable">Unavailable</option></select></label>
        <label>From sequence<input aria-label="Evidence from sequence" type="number" min="1" value={filters.from_sequence ?? ''} onChange={(event) => updateFilter('from_sequence', optionalNumber(event.target.value))} /></label>
        <label>To sequence<input aria-label="Evidence to sequence" type="number" min="1" value={filters.to_sequence ?? ''} onChange={(event) => updateFilter('to_sequence', optionalNumber(event.target.value))} /></label>
        <label>Relevant reference<input aria-label="Evidence relevant reference" value={filters.relevant_ref ?? ''} onChange={(event) => updateFilter('relevant_ref', event.target.value)} /></label>
        <label>Sort<select aria-label="Evidence sort" value={filters.sort ?? ''} onChange={(event) => updateFilter('sort', event.target.value === '' ? null : event.target.value as 'producer_sequence' | 'verification_status')}><option value="">Recorded order</option><option value="producer_sequence">Producer sequence</option><option value="verification_status">Verification status</option></select></label>
      </div>
    </header>

    <p className="evidence-filter-summary" aria-live="polite">{rows.length} loaded evidence records{loadedRange ? ` · sequences ${loadedRange[0]}–${loadedRange[1]}` : ''}</p>
    <div ref={setScrollElement} className="evidence-virtual-scroll">
      <EvidencePagination hasOlder={hasOlder} state={olderState} error={olderError} onLoad={onLoadOlder} onRetry={onRetryOlder} />
      {rows.length === 0 ? <p className="unavailable">No evidence artifacts match the current filters.</p> : <div role="treegrid" aria-label="Evidence artifacts" aria-rowcount={rows.length + 1} aria-busy={olderState === 'loading' ? 'true' : 'false'} className="evidence-grid">
        <div role="row" className="evidence-head"><span role="columnheader">Artifact / type</span><span role="columnheader">Source / verification</span><span role="columnheader">Producer / consumers</span><span role="columnheader">Actions</span></div>
        <div role="rowgroup" className="evidence-rowgroup" style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualRows.map((virtualRow) => {
            const record = rows[virtualRow.index];
            if (!record) return null;
            const selected = selectedRefs.includes(record.reference);
            const verified = record.verification_status === 'verified';
            return <div
              key={virtualRow.key}
              ref={virtualizer.measureElement}
              data-index={virtualRow.index}
              role="row"
              aria-rowindex={virtualRow.index + 2}
              aria-selected={selected}
              className={selected ? 'evidence-row selected' : 'evidence-row'}
              style={{ position: 'absolute', width: '100%', transform: `translateY(${virtualRow.start}px)` }}
            >
              <span role="gridcell"><button type="button" className="evidence-reference" onClick={() => onSelectRef(record.reference)} aria-label={`${record.kind} · ${record.reference} · ${record.verification_status}`}><strong>{record.kind}</strong><span>{record.reference}</span></button>{record.relative_path ? <small>{record.relative_path}</small> : null}</span>
              <span role="gridcell"><SourceBadge source={record.source} /><small>{record.verification_status}</small>{!verified ? <small className="evidence-blocked-reason">{unavailableReason(record)}</small> : null}</span>
              <span role="gridcell" className="evidence-lineage"><EvidenceLineage record={record} onSelectSequence={onSelectSequence} /></span>
              <span role="gridcell" className="evidence-actions">
                <button type="button" onClick={() => void copyReference(record.reference)}>Copy reference</button>
                {verified ? <><button type="button" onClick={() => void openPreview(record)} aria-label={`Preview ${record.reference}`}>Preview</button><a href={artifactUrl(record.reference)} download>Download</a></> : <small>Preview and download blocked.</small>}
              </span>
            </div>;
          })}
        </div>
      </div>}
    </div>
    {copyStatus ? <p className="visually-hidden" role="status">{copyStatus}</p> : null}

    {previewState ? <aside className="evidence-preview" aria-label="Artifact preview">
      <header><div><h2>{previewState.reference}</h2><p>Display-only registered artifact preview.</p></div><button type="button" onClick={closePreview}>Close preview</button></header>
      {previewState.state === 'loading' ? <p role="status">Loading bounded preview…</p>
        : previewState.state === 'failed' ? <p role="alert">{previewState.error}</p>
          : previewState.preview ? <><p className="evidence-preview-meta">{previewState.preview.kind} · {previewState.preview.truncated ? 'truncated at 131072 bytes' : 'complete response'}</p><pre>{previewState.preview.content}</pre></> : null}
    </aside> : null}
  </section>;
}
