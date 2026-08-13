# Analysis Context Architecture

This document is the maintained contract for continuous static-analysis runs.
The checked-in machine schemas are `schemas/analysis-context-v1.schema.json`
for the materialized snapshot and `schemas/analysis-context-event-v1.schema.json`
for the append-only ledger event format.

## Ownership Boundaries

`grid-agent` owns the continuous analysis workspace, copied input ledger,
turn lifecycle, Pi runtime launch, compact model-facing context view, answer
draft acceptance, trace redaction, and final report projection. `gridctl`
owns simulator-side state, pandapower execution, deterministic result/evidence
artifacts, and every numerical or network-specific claim. Pi may only interact
with project-defined grid tools, `grid_guide_open`, and `grid_submit_answer`;
it must not receive shell, generic file I/O, raw pandapower objects, arbitrary
Python, or legacy query aliases.

Simulator-backed runs write current-run evidence under `runs/<analysis_id>/`.
Offline informational answers do not create analysis context evidence.

## State and Event Schemas

The durable snapshot has `schema_version: "analysis-context/1.0"` and is
validated by `schemas/analysis-context-v1.schema.json`. It contains input and
runtime records, the active simulator baseline, the current turn, completed
turns, observations, registered result artifacts, registered evidence,
verified facts, diagnostics, and unresolved limitations.

The ledger event has `schema_version: "analysis-context-event/1.0"` and is
validated by `schemas/analysis-context-event-v1.schema.json`. Every event
records `analysis_id`, monotonic `sequence`, `previous_revision`,
`previous_state_hash`, `next_revision`, `next_state_hash`, and `integrity`
(`verified` or `diagnostic`). Normative event names are:

- `analysis.started`
- `turn.started`
- `simulator.context.opened`
- `tool.observation.recorded`
- `result.registered`
- `evidence.registered`
- `fact.verified`
- `tool.failed`
- `answer.submitted`
- `audit.diagnostic.recorded`
- `limitation.recorded`
- `limitation.resolved`
- `turn.completed`
- `analysis.completed`
- `analysis.failed`

## Lifecycle and State Machine

A ledger begins with `analysis.started`, which materializes input/runtime
records and revision 1. Each instruction then opens exactly one active turn
with `turn.started`. During the active turn, semantic tool events are reduced
into observations, baselines, results, evidence, facts, diagnostics, and
limitations. `turn.completed` closes the active turn and snapshots consumed
and produced references. After all turns close successfully,
`analysis.completed` finalizes the run; terminal setup, Pi, simulator, or
integrity failures record `analysis.failed` when no active turn remains.

No new turn may begin while `current_turn` is set. Result and evidence
registration requires an active matching turn unless the reducer explicitly
allows a global diagnostic. Replay of `context/context-events.jsonl` must
equal `context/analysis-context.json` and the in-memory snapshot.

## Event-to-State Reduction Rules

`analysis.started` creates the initial snapshot from the copied instruction
record and runtime record. `turn.started` records ordinal, instruction hash,
and nonce hash. `simulator.context.opened` upserts a baseline and sets
`active_context_ref`. `tool.observation.recorded` stores canonical tool input
and compact output summaries; its `consumed_refs` and `produced_refs` are
merged into the active turn. `result.registered` admits a verified result
artifact whose `revision_ref` matches the active baseline. `evidence.registered`
admits simulator evidence and links it to known refs. `fact.verified` promotes
small, model-usable fact statements from verified simulator artifacts only.
`tool.failed`, `audit.diagnostic.recorded`, and diagnostic
`limitation.recorded` events preserve failure evidence without inventing an
answer. `limitation.resolved` removes an unresolved limitation by reference.
`turn.completed` archives the accepted answer JSON path and freezes per-turn
ref lineage. `analysis.completed` and `analysis.failed` set terminal status.
`answer.submitted` is reserved for explicit answer submission events; accepted
per-turn answers are currently represented by archived answer files plus
`turn.completed`.

## Content Integrity and Failure Boundaries

All numerical, voltage, loss, ranking, topology, and contingency statements
must cross the simulator boundary through `gridctl` using
`grid-capability` protocol version `1.0` and pinned pandapower `3.4.0`.
`grid-agent` verifies simulator-produced refs before admitting them to the
context. A successful simulator result without a matching tool start, with
mismatched started inputs, missing artifacts, corrupted content hashes, or
unregistered dependencies fails the turn and prevents later turns from
continuing on untrusted state. Audit diagnostics do not replace accepted
answers; they are diagnostic events and report annotations.

Standard traces store semantic RPC events only. Streaming token deltas,
reasoning deltas, and repeated message snapshots are excluded from
`trace/events.jsonl`.

`analysis_context.changed` and `analysis_context.injected` are trace-only
lifecycle records. They carry the view revision/state hash (and injection path)
for every model injection, but never enter the authoritative context ledger or
change its revision. Tool-derived context events retain their compact RPC
`trace_sequence` in that ledger.

## Model-facing Context View

Before every prompt, `grid-agent` writes
`context/analysis-context-view.json` (`analysis-context-view/1.0`) and passes
that bounded view to Pi. The view includes the current revision and state hash,
the active baseline, the active turn, completed turn summaries, reusable
results, verified facts grouped by predicate, and unresolved limitations. It
must preserve provenance fields (`result_ref`, `revision_ref`, `evidence_refs`,
`producer_observation`) rather than truncating references. Large simulator
tables are omitted from the view and remain available only through registered
artifacts and follow-on grid tools.

## Report Projection

`report.md` is a projection from the finalized context and workspace files. It
must display one global simulator baseline table, final context links,
result/evidence/observation dependencies, and a per-turn timeline. Every turn
shows status, accepted answer file, exact `answer_output`, reused prior refs,
newly produced artifacts, and the context revision range labeled
`上下文版本`. Report diagnostics may explain missing or malformed artifacts, but
the report must not infer simulator facts absent from the context.

## Schema Evolution Rules

Compatible additions to `analysis-context/1.0` or
`analysis-context-event/1.0` require optional fields only and regenerated
checked-in schemas. Incompatible changes require a new schema version such as
`analysis-context/2.0` plus a new schema file, and event readers must keep
replay support for existing `analysis-context-event/1.0` ledgers or provide a
documented migration.

## Topology Example

Capability input:

```json
{"capability":"topology.branch.endpoints.get","arguments":{"context_ref":"context:sha256:...","kind":"line","namespace":"pandapower_index","identifier":"11"}}
```

Emitted context event types: `tool.observation.recorded`,
`evidence.registered`, and `fact.verified`. Registered references include the
consumed `context_ref` and an `evidence:sha256:...` network-fact artifact.
Promoted facts have statements shaped like
`{"predicate":"topology.branch.from_bus","branch_ref":"asset:line:...","value":"asset:bus:..."}` and
`{"predicate":"topology.branch.to_bus","branch_ref":"asset:line:...","value":"asset:bus:..."}`.
The report projection shows the observation/evidence dependency rows and the
turn answer that cites the accepted topology evidence.

## AC Power Flow and Ranking Example

Power-flow capability input:

```json
{"capability":"analysis.powerflow.ac.run","arguments":{"context_ref":"context:sha256:..."}}
```

Emitted context event types: `tool.observation.recorded`,
`simulator.context.opened` when the baseline is first seen,
`result.registered`, `evidence.registered`, and `fact.verified`. Registered
references include `result:sha256:...` for the persisted power-flow result and
`evidence:sha256:...` for simulator evidence. Promoted facts include
`{"predicate":"powerflow.converged","value":true}` and
`{"predicate":"powerflow.total_active_loss","value":{"value":43.6411257608517,"unit":"MW"}}`.

The ranking turn must reuse the exact prior result reference:

```json
{"capability":"result.branches.rank","arguments":{"result_ref":"result:sha256:...","metric":"loading_percent","direction":"descending","limit":5,"element_kind":"line"}}
```

Emitted context event types are `tool.observation.recorded` and
`fact.verified`; ranking does not register a new result artifact. The
observation consumes the prior power-flow `result_ref`; promoted facts are
shaped like
`{"predicate":"branch.loading_percent","branch_ref":"asset:line:...","rank":1,"value":73.37094458210946,"unit":"percent"}`.
The report projection for the ranking turn lists the power-flow result under
reused refs and shows no fabricated ranking artifact.

## N-1 Example

Capability input:

```json
{"capability":"analysis.contingency.n_minus_one.run","arguments":{"context_ref":"context:sha256:...","branch_refs":["asset:line:..."],"policy":"static-analysis-v1"}}
```

The branch reference should come from a prior verified topology or ranking
fact. Emitted context event types are `tool.observation.recorded`,
`result.registered`, `evidence.registered`, and `fact.verified`. Registered
references include an aggregate `result:sha256:...`, scenario result refs
inside that artifact, and scenario `evidence:sha256:...` refs. Promoted facts
include
`{"predicate":"n1.status","value":"succeeded"}`,
`{"predicate":"n1.scenario_count","value":1}`,
`{"predicate":"n1.max_loading_percent","value":103.4,"unit":"%"}`, and
`{"predicate":"n1.violation_count","value":1}`. The report projection lists
the N-1 result and evidence dependencies, the copied input, the context ledger,
the compact trace, and the turn-level context revision change.
