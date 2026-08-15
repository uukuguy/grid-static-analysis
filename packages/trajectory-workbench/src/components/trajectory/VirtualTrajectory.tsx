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
  estimateSize?: (item: T) => number;
}

/** A bounded, semantic-ID keyed list shared by the trajectory projections. */
export function VirtualTrajectory<T extends TrajectoryItem>({
  items, label, renderRow, onRequestOlder, hasOlder = false, estimateSize = () => 84,
}: VirtualTrajectoryProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [scrollElement, setScrollElement] = useState<HTMLDivElement | null>(null);
  const previousIds = useRef<string[]>(items.map((item) => item.id));
  const pendingAnchor = useRef<PrependAnchor | null>(null);
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
  const renderedItems = virtualItems.length > 0 ? virtualItems : items.slice(0, 16).map((_, index) => ({
    index, key: items[index].id, start: index * estimateSize(items[index]),
  }));

  return (
    <div ref={(node) => { parentRef.current = node; setScrollElement(node); }} className="virtual-scroll" onScroll={() => {
      if (hasOlder && (virtualizer.scrollOffset ?? 0) < 32) requestOlder();
    }}>
      {hasOlder && <button type="button" className="load-older" onClick={requestOlder}>Load older history</button>}
      <div role="list" aria-label={label} aria-busy="false" style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {renderedItems.map((row) => {
          const item = items[row.index];
          return <div
            key={row.key}
            ref={virtualizer.measureElement}
            data-index={row.index}
            data-testid={item.id}
            role="listitem"
            aria-posinset={row.index + 1}
            aria-setsize={items.length}
            style={{ position: 'absolute', width: '100%', transform: `translateY(${row.start}px)` }}
          >{renderRow(item)}</div>;
        })}
      </div>
    </div>
  );
}
