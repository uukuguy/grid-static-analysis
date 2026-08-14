import type { ReactNode } from 'react';

export interface WorkbenchShellProps {
  explorer: ReactNode;
  header: ReactNode;
  timeline: ReactNode;
  content: ReactNode;
  inspector: ReactNode;
  focusedTurnId?: string | null;
}

export function WorkbenchShell({ explorer, header, timeline, content, inspector, focusedTurnId }: WorkbenchShellProps) {
  return <div className="workbench-shell">
    <header className="topbar">{header}</header>
    <aside className="run-rail">{explorer}</aside>
    <section className="timeline-region" aria-label="Run overview timeline" data-focused-turn={focusedTurnId ?? undefined}>{timeline}</section>
    <main className="trajectory-main">{content}</main>
    <aside className="inspector" aria-label="Trajectory inspector">{inspector}</aside>
  </div>;
}
