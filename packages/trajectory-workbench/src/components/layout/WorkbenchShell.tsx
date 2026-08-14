import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';

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
  const [inspectorOpen, setInspectorOpen] = useState(false);
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

  return <div className="workbench-shell">
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
    </> : <aside className="inspector" aria-label="Trajectory inspector">{inspector}</aside>}
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
  const query = '(max-width: 720px)';
  const [isMobile, setIsMobile] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return isMobile;
}
