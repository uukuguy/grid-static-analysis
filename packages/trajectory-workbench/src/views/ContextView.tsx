import { useState } from 'react';
import type { ContextFrame, JsonValue } from '../api/types';

interface ContextViewProps { frame: ContextFrame | null; onSelectSequence: (sequence: number) => void; artifactUrl: (ref: string) => string; }
const labels = ['Before', 'Delta', 'After'] as const;

function JsonDocument({ value }: { value: JsonValue }) { return <pre className="json-document">{JSON.stringify(value, null, 2)}</pre>; }
function TypedDelta({ value }: { value: Record<string, JsonValue> }) { const entries = Object.entries(value); return entries.length ? <dl className="typed-delta">{entries.map(([key, entry]) => <div key={key}><dt>{key}</dt><dd>{typeof entry === 'string' ? entry : JSON.stringify(entry)}</dd></div>)}</dl> : <p>No recorded state change.</p>; }

export function ContextView({ frame, onSelectSequence, artifactUrl }: ContextViewProps) {
  const [active, setActive] = useState<typeof labels[number]>('Before');
  if (!frame) return <section className="context-view" aria-label="Context time travel"><h1>Context time travel</h1><p className="unavailable">No context frame is available for the selected event.</p></section>;
  const panels = { Before: <JsonDocument value={frame.before_state} />, Delta: <TypedDelta value={frame.delta} />, After: <JsonDocument value={frame.after_state} /> };
  return <section className="context-view" aria-label="Context time travel"><header><h1>Context time travel</h1><p>Authoritative state at sequence {frame.source_sequence}; revisions {frame.before_revision} → {frame.after_revision}.</p></header>
    <label className="sequence-scrubber">Event sequence <input type="range" min={1} max={Math.max(1, frame.max_sequence)} value={frame.source_sequence} onChange={(event) => onSelectSequence(Number(event.target.value))} /><output>{frame.source_sequence}</output></label>
    <div role="tablist" aria-label="Context state"><>{labels.map((label) => <button key={label} type="button" role="tab" aria-selected={active === label} onClick={() => setActive(label)}>{label}</button>)}</></div>
    <section role="tabpanel" aria-label={`${active} context state`} className="context-panel">{panels[active]}</section>
    <section className="request-input" aria-label="Model-visible request input"><h2>Model-visible request input</h2>{frame.request_artifact_ref ? <a href={artifactUrl(frame.request_artifact_ref)} download>{frame.request_artifact_ref}</a> : <p className="unavailable">{frame.unavailable_reason || 'No following model request'}</p>}</section>
  </section>;
}
