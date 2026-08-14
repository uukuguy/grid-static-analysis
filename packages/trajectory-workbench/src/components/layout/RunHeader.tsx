import type { KeyboardEvent } from 'react';
import type { RunSummary } from '../../api/types';
import type { WorkbenchView } from '../../state/workbench';
import type { ResolvedTheme } from '../../design/theme';

const views: WorkbenchView[] = ['business', 'agent', 'context', 'evidence'];
const labels: Record<WorkbenchView, string> = { business: 'Business', agent: 'Agent', context: 'Context', evidence: 'Evidence' };

interface RunHeaderProps {
  run: RunSummary | null;
  activeView: WorkbenchView;
  onViewSelect: (view: WorkbenchView) => void;
  theme: ResolvedTheme;
  onThemeToggle: () => void;
}

export function RunHeader({ run, activeView, onViewSelect, theme, onThemeToggle }: RunHeaderProps) {
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + views.length) % views.length;
    document.getElementById(`workbench-tab-${views[next]}`)?.focus();
  };
  return <div className="run-header">
    <div className="brand"><span className="brandmark" aria-hidden="true" />Grid Agent <span>/ Trajectory</span></div>
    <div className="run-title"><strong>{run?.analysis_id ?? 'Select a run'}</strong><small>{run?.source_kind ?? 'No run loaded'} · {run?.turn_count ?? 0} turns</small></div>
    <div className="status-chip">{run?.status ?? 'idle'}</div>
    <button type="button" className="theme-toggle" onClick={onThemeToggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
      {theme === 'dark' ? 'Light theme' : 'Dark theme'}
    </button>
    <div role="tablist" aria-label="Trajectory views" className="view-tabs">
      {views.map((view, index) => <button key={view} id={`workbench-tab-${view}`} type="button" role="tab"
        aria-selected={activeView === view} aria-controls={`workbench-panel-${view}`} tabIndex={activeView === view ? 0 : -1}
        onClick={() => onViewSelect(view)} onKeyDown={(event) => onKeyDown(event, index)}>{labels[view]}</button>)}
    </div>
  </div>;
}
