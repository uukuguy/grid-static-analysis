import { useEffect, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

export interface TrajectoryItem {
  id: string;
  source_sequence: number;
}

export interface PrependAnchor {
  itemId: string;
  offset: number;
  focusedId: string | null;
}

interface VirtualTrajectoryProps<T extends TrajectoryItem> {
  items: T[];
  label: string;
  renderRow: (item: T) => React.ReactNode;
  onRequestOlder: (anchor: PrependAnchor) => void;
  hasOlder?: boolean;
  olderState?: 'idle' | 'loading' | 'failed';
  olderError?: string | null;
  onRetryOlder?: () => void;
  estimateSize?: (item: T) => number;
  focusItemId?: string | null;
  focusElementId?: string | null;
}

/** A bounded, semantic-ID keyed list shared by the trajectory projections. */
export function VirtualTrajectory<T extends TrajectoryItem>({
  items, label, renderRow, onRequestOlder, hasOlder = false, olderState = 'idle', olderError = null, onRetryOlder = () => undefined,
  estimateSize = () => 84, focusItemId = null, focusElementId = null,
}: VirtualTrajectoryProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const previousIds = useRef<string[]>(items.map((item) => item.id));
  const pendingAnchor = useRef<PrependAnchor | null>(null);
  const pendingFocus = useRef<{ itemId: string; elementId: string | null } | null>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollElement,
    estimateSize: (index) => estimateSize(items[index]),
    getItemKey: (index) => items[index].id,
    overscan: 8,
    useFlushSync: false,
    initialRect: { width: 900, height: 700 },
  });

  useEffect(() => {
    virtualizer.measure();
  }, [virtualizer]);

  useEffect(() => {
    if (!focusItemId) return;
    const index = items.findIndex((item) => item.id === focusItemId);
    if (index < 0) return;
    pendingFocus.current = { itemId: focusItemId, elementId: focusElementId };
    virtualizer.scrollToIndex(index, { align: 'center' });
  }, [focusElementId, focusItemId, items, virtualizer]);

  useEffect(() => {
    const anchor = pendingAnchor.current;
    if (!anchor || previousIds.current.length >= items.length) {
      previousIds.current = items.map((item) => item.id);
      return;
    }
    const index = items.findIndex((item) => item.id === anchor.itemId);
    const measurement = virtualizer.getOffsetForIndex(index, 'start');
    if (measurement) virtualizer.scrollToOffset(measurement[0] - anchor.offset);
    if (anchor.focusedId) document.getElementById(anchor.focusedId)?.focus({ preventScroll: true });
    pendingAnchor.current = null;
    previousIds.current = items.map((item) => item.id);
  }, [items, virtualizer]);

  const requestOlder = () => {
    if (olderState !== 'idle') return;
    const first = virtualizer.getVirtualItems()[0];
    const index = first?.index ?? 0;
    const item = items[index];
    if (!item) return;
    const focused = document.activeElement instanceof HTMLElement ? document.activeElement.id || null : null;
    const anchor = { itemId: item.id, offset: (first?.start ?? 0) - (virtualizer.scrollOffset ?? 0), focusedId: focused };
    pendingAnchor.current = anchor;
    onRequestOlder(anchor);
  };
  // A deterministic initial window keeps the list usable before layout observation settles
  // (including embedded and test environments that report a zero-size scroll container).
  const virtualItems = virtualizer.getVirtualItems();
  const baseRenderedItems = virtualItems.length > 0 ? virtualItems : items.slice(0, 16).map((_, index) => ({
    index, key: items[index].id, start: index * estimateSize(items[index]),
  }));
  const focusIndex = focusItemId ? items.findIndex((item) => item.id === focusItemId) : -1;
  const renderedItems = focusIndex >= 0 && !baseRenderedItems.some((row) => row.index === focusIndex)
    ? [...baseRenderedItems, { index: focusIndex, key: items[focusIndex].id, start: estimatedOffset(items, focusIndex, estimateSize) }]
    : baseRenderedItems;

  useEffect(() => {
    const focus = pendingFocus.current;
    if (!focus) return;
    const target = focus.elementId
      ? document.getElementById(focus.elementId)
      : Array.from(document.querySelectorAll<HTMLElement>('[data-focus-item-id]')).find((element) => element.dataset.focusItemId === focus.itemId) ?? null;
    if (!target) return;
    target.focus({ preventScroll: true });
    pendingFocus.current = null;
  }, [renderedItems]);

  return (
    <div ref={(node) => { parentRef.current = node; setScrollElement(node); }} className="virtual-scroll" onScroll={() => {
      if (hasOlder && olderState === 'idle' && (virtualizer.scrollOffset ?? 0) < 32) requestOlder();
    }}>
      {hasOlder || olderState !== 'idle' ? <PaginationControl
        state={olderState}
        error={olderError}
        onLoad={requestOlder}
        onRetry={onRetryOlder}
      /> : null}
      <div role="list" aria-label={label} aria-busy={olderState === 'loading' ? 'true' : 'false'} style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {renderedItems.map((row) => {
          const item = items[row.index];
          return <div
            key={row.key}
            ref={virtualizer.measureElement}
            data-index={row.index}
            data-testid={item.id}
            data-focus-item-id={item.id}
            role="listitem"
            tabIndex={focusItemId === item.id && !focusElementId ? -1 : undefined}
            aria-posinset={row.index + 1}
            aria-setsize={items.length}
            style={{ position: 'absolute', width: '100%', transform: `translateY(${row.start}px)` }}
          >{renderRow(item)}</div>;
        })}
      </div>
    </div>
  );
}

function PaginationControl({
  state, error, onLoad, onRetry,
}: {
  state: 'idle' | 'loading' | 'failed';
  error: string | null;
  onLoad: () => void;
  onRetry: () => void;
}) {
  if (state === 'loading') {
    return <button type="button" className="load-older" disabled>Loading older history</button>;
  }
  if (state === 'failed') {
    return <div className="load-older older-history-error" role="status">
      {error ? <span>{error}</span> : null}
      <button type="button" onClick={onRetry}>Retry older history</button>
    </div>;
  }
  return <button type="button" className="load-older" onClick={onLoad}>Load older history</button>;
}

function estimatedOffset<T extends TrajectoryItem>(items: T[], index: number, estimateSize: (item: T) => number) {
  let offset = 0;
  for (let cursor = 0; cursor < index; cursor += 1) offset += estimateSize(items[cursor]);
  return offset;
}
