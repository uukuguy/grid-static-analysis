# Trajectory Event Protocol

This document is the normative contract for native trajectory events written
by `grid-agent`. The machine-readable schema for this version is
`schemas/grid-run-event-v1.schema.json`, generated from
`RunEvent.model_json_schema()` by `scripts/update_trajectory_schemas.py`.

## Authority and Workspace Layout

`events/run-events.jsonl` is the authoritative, append-only event spine for a
native run. The following paths are part of the run workspace contract:

```text
runs/<analysis_id>/
  events/run-events.jsonl
  requests/
  projections/agent-trajectory.json
  projections/business-trajectory.json
  projections/context-timeline.json
  projections/artifact-index.json
```

The projection files are rebuildable views and never competing sources of
truth. Existing input, output, context, evidence, tool-result, turn, trace,
Pi, manifest, and report paths remain supported. In particular,
`context/context-events.jsonl` and `trace/events.jsonl` are compatibility
surfaces, not the native event authority.

## Envelope and Integrity

Every `grid-run-event/1.0` record is a JSON object with these required
members: `schema_version`, `analysis_id`, `sequence`, `timestamp`,
`event_type`, `previous_event_hash`, `event_hash`, `scope`, `causation`,
`source`, `context`, `refs`, and `payload`.

`sequence` starts at `1` and is contiguous. The first record uses the
protocol zero hash (`sha256:` followed by 64 zeroes) as
`previous_event_hash`; every later record repeats the preceding event's
`event_hash`. Native timestamps are canonical UTC instants with microsecond
precision.

`event_hash` is `sha256:` plus the SHA-256 digest of canonical UTF-8 JSON for
the full event excluding its own `event_hash` member. Canonical JSON sorts
object keys, preserves list order, rejects non-finite numbers, has no
insignificant whitespace, and ends with a newline. The hash chain proves the
order and content of the trusted event prefix.

## Source, Scope, and References

`source.kind` is one of `observed` or `agent-declared`; `source.producer` and
`source.integrity` are non-empty producer and integrity labels. A derived
projection is not a source kind: it cites the source sequences from which it
was rebuilt.

`scope` has an optional, strictly nested identity chain:
`turn_id` → `step_id` → `request_id` → `tool_call_id`. A step requires its
turn, a request requires its step, and a tool call requires its request.
`causation.parent_sequence` identifies a direct cause when known, while
`causation.correlation_id` groups related lifecycle events. No relationship is
invented when it is ambiguous.

`refs.consumed`, `refs.produced`, and `refs.evidence` contain non-empty
current-run references. `context.before_revision` and `after_revision`
identify the surrounding analysis-context state; an event with no context
change records the same revision on both sides.

## Event Vocabulary and Payloads

The required `grid-run-event/1.0` vocabulary is closed. Each event payload is
validated by its event-specific Pydantic model and rejects undeclared fields.

```text
analysis.started
analysis.completed
analysis.failed
turn.started
turn.completed
turn.failed
step.started
step.completed
step.failed
model.request.started
model.response.completed
model.response.failed
model.retry.scheduled
model.retry.started
model.retry.exhausted
tool.started
tool.completed
tool.failed
business.decision.declared
business.claim.declared
context.projected
context.injected
answer.submitted
answer.rejected
audit.diagnostic.recorded
```

`model.request.started` and `model.response.completed` cite immutable request
artifacts under `requests/<request_id>/input.json` and
`requests/<request_id>/response.json`. Events record bounded summaries and
artifact references rather than hidden reasoning or streaming token deltas.

## Recorder and Artifact Rules

`RunEventRecorder` is the only native writer of `run-events.jsonl`. It
validates a typed draft, rejects prohibited secrets and hidden-reasoning
content, assigns sequence and timestamp, computes the hash, appends canonical
JSON, flushes and fsyncs it, then notifies best-effort subscribers. A recorder
append or ownership failure is terminal: the analysis must not continue
producing answers after losing its authoritative history.

Artifact-before-event is mandatory. An immutable artifact must be committed
and digest-verified before an event may reference it. A tool result artifact,
for example, is persisted before `tool.completed` cites it. Artifact integrity
or registration failure therefore prevents the dependent event from becoming
authoritative.

## Fail-Closed Reading and Evolution

Trusted replay accepts only JSON-native finite values, the complete validated
envelope, contiguous sequence numbers, the expected previous hash, and a
matching recomputed event hash. On malformed JSON, an invalid envelope, a
sequence gap, invalid nested scope, hash mismatch, impossible transition, or
unknown required event, replay stops at the last valid sequence. It does not
merge the invalid suffix into business conclusions.

Compatible protocol changes add only optional fields with documented absence
semantics and regenerate the checked-in schema. Incompatible envelope or
payload semantics require a new schema version and an explicit reader or
importer. Readers must refuse unknown required event semantics rather than
silently reconstructing a truncated trajectory.
