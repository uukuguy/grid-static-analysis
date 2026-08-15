import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';

export interface WorkbenchShellProps {
  explorer: ReactNode;
  header: ReactNode;
  timeline: ReactNode;
  content: ReactNode;
  inspector: ReactNode;
  focusedTurnId?: string | null;
}

export function WorkbenchShell({ explorer, header, timeline, content, inspector, focusedTurnId }: WorkbenchShellProps) {
  const isMobile = useMobileInspector();
  const isMedium = useMediumInspector();
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState<number | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!isMobile) setInspectorOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (isMobile && inspectorOpen) closeRef.current?.focus();
  }, [inspectorOpen, isMobile]);

  const closeInspector = () => {
    setInspectorOpen(false);
    triggerRef.current?.focus();
  };
  const trapInspectorFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeInspector();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(sheetRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]',
    ) ?? []).filter(isTabbable);
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const resizeInspector = (event: PointerEvent<HTMLDivElement>) => {
    const initialWidth = event.currentTarget.parentElement?.querySelector<HTMLElement>('.inspector')?.getBoundingClientRect().width;
    if (!initialWidth) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const resize = (move: globalThis.PointerEvent) => setInspectorWidth(clampInspectorWidth(initialWidth + startX - move.clientX));
    const stop = () => {
      window.removeEventListener('pointermove', resize);
      window.removeEventListener('pointerup', stop);
    };
    window.addEventListener('pointermove', resize);
    window.addEventListener('pointerup', stop, { once: true });
  };
  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const currentWidth = inspectorWidth ?? window.innerWidth * 0.42;
    setInspectorWidth(clampInspectorWidth(currentWidth + (event.key === 'ArrowLeft' ? 24 : -24)));
  };

  const shellStyle = isMedium && inspectorWidth !== null ? { '--inspector-width': `${inspectorWidth}px` } as CSSProperties : undefined;
  return <div className="workbench-shell" style={shellStyle}>
    <header className="topbar">{header}</header>
    <aside className="run-rail">{explorer}</aside>
    <section className="timeline-region" aria-label="Run overview timeline" data-focused-turn={focusedTurnId ?? undefined}>{timeline}</section>
    <main className="trajectory-main">{content}</main>
    {isMobile ? <>
      <button ref={triggerRef} type="button" className="inspector-trigger" aria-haspopup="dialog" aria-expanded={inspectorOpen} aria-controls="mobile-trajectory-inspector" onClick={() => setInspectorOpen(true)}>Open inspector</button>
      {inspectorOpen ? <div className="inspector-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeInspector(); }}>
        <aside ref={sheetRef} id="mobile-trajectory-inspector" className="inspector inspector-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-trajectory-inspector-title" onKeyDown={trapInspectorFocus}>
          <div className="inspector-sheet-header"><h2 id="mobile-trajectory-inspector-title">Trajectory inspector</h2><button ref={closeRef} type="button" onClick={closeInspector}>Close inspector</button></div>
          {inspector}
        </aside>
      </div> : null}
    </> : <>
      {isMedium ? <div className="inspector-resize-handle" role="separator" aria-label="Resize trajectory inspector" aria-orientation="vertical" tabIndex={0} onPointerDown={resizeInspector} onKeyDown={resizeWithKeyboard} /> : null}
      <aside className="inspector" aria-label="Trajectory inspector">{inspector}</aside>
    </>}
  </div>;
}

function isTabbable(element: HTMLElement) {
  const style = window.getComputedStyle(element);
  return element.tabIndex >= 0
    && !element.matches(':disabled')
    && !element.closest('[hidden], [aria-hidden="true"]')
    && style.display !== 'none'
    && style.visibility !== 'hidden';
}

function useMobileInspector() {
  return useMediaQuery('(max-width: 799px)');
}

function useMediumInspector() {
  return useMediaQuery('(min-width: 800px) and (max-width: 1199px)');
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return matches;
}

function clampInspectorWidth(width: number) {
  return Math.min(Math.round(window.innerWidth * 0.63), Math.max(300, Math.round(width)));
}
