import type { ReactNode } from 'react';

export type AsyncStateName = 'idle' | 'loading' | 'ready' | 'empty' | 'partial' | 'corrupt' | 'unsupported' | 'network-error';

interface AsyncStateProps {
  state: AsyncStateName;
  diagnostic?: string | null;
  onRetry?: () => void;
  children?: ReactNode;
}

const copy: Record<Exclude<AsyncStateName, 'idle' | 'ready'>, { title: string; detail: string }> = {
  loading: { title: 'Loading runs', detail: 'Fetching the recorded trajectory runs.' },
  empty: { title: 'No runs available', detail: 'This workspace does not contain a recorded trajectory run yet.' },
  partial: { title: 'Run is partial', detail: 'Only the recorded portion of this run is available.' },
  corrupt: { title: 'Run data is corrupt', detail: 'This run cannot be safely displayed.' },
  unsupported: { title: 'Run data is unsupported', detail: 'This workbench version cannot display this trajectory resource.' },
  'network-error': { title: 'Unable to load runs', detail: 'The trajectory API could not be reached. Try again.' },
};

export function AsyncState({ state, diagnostic, onRetry, children }: AsyncStateProps) {
  if (state === 'ready') return <>{children}</>;
  if (state === 'idle') return null;
  const message = copy[state];
  return <section className={`async-state state-${state}`} data-testid={`state-${state}`} role={state === 'network-error' ? 'alert' : 'status'} aria-live="polite">
    <h2>{message.title}</h2>
    <p>{diagnostic ?? message.detail}</p>
    {state === 'network-error' && onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
  </section>;
}
