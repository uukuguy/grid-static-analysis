# Analysis Context Architecture

This document is the maintained contract for continuous static-analysis runs.
The checked-in machine schemas are `schemas/analysis-context-v1.schema.json`
for the materialized snapshot and `schemas/analysis-context-event-v1.schema.json`
for the append-only ledger event format.

## Ownership Boundaries

`grid-agent` owns the continuous analysis workspace, copied input ledger,
turn lifecycle, Pi runtime launch, compact model-facing context view,
controller-owned answer submission, trace redaction, and final report
projection. `gridctl` owns simulator-side state, pandapower execution,
deterministic result/evidence artifacts, and every numerical or
network-specific claim. Pi may only interact with project-defined grid tools
and `grid_guide_open`; it must not receive shell, generic file I/O, raw
pandapower objects, arbitrary Python, legacy query aliases, or a model-visible
answer persistence tool. The model returns reader-facing final text, and
`grid-agent` binds current-turn result/evidence references before committing
the answer deterministically.

Simulator-backed runs write current-run evidence under `runs/<analysis_id>/`.
Offline informational answers do not create analysis context evidence.

## Four-Layer Context Architecture

Continuous analysis has four explicit layers:

1. The **ledger kernel** appends validated events and deterministically replays
   the snapshot. It owns ordering, hashes, turns, and current-run integrity.
2. The **capability catalog** reads simulator contracts. Their `context_effect`
   selects a projector and declares required, consumed, produced, and
   invalidated semantic state.
3. The typed **domain state** stores pandapower meaning rather than question
   answers. It is the `domain_state` field in the durable snapshot.
4. The **bounded agent view** selects the active model revision and concise,
   source-bearing summaries for the next prompt. Full history stays in the
   ledger and artifacts.

No layer branches on question number, validation wording, or expected answer.
Capability contracts and verified result shapes select projection.

## State and Event Schemas

The durable snapshot has `schema_version: "analysis-context/1.0"` and is
validated by `schemas/analysis-context-v1.schema.json`. It contains input and
runtime records, the active simulator baseline, the current turn, completed
turns, observations, registered result artifacts, registered evidence,
verified facts, diagnostics, and unresolved limitations.

New Analysis runs use `events/run-events.jsonl` as the authoritative native
trajectory. Its `grid-run-event/1.0` envelopes form one replay-verified hash
chain across model requests, public model responses, tools, context changes,
accepted answers, and terminal lifecycle events. The manifest publishes this
path as `events_path` together with `trajectory_schema_version`.

Before each provider call in a native continuous analysis, Pi writes the final
provider-independent semantic request to
`requests/<request_id>/input.json` (`grid-model-request-input/2.0`). This
request is committed and acknowledged before provider I/O begins. It is the
canonical replay boundary for model-facing context: final system prompt,
messages, public tool schemas, public options, correlations, runtime identity,
and semantic digest. Provider wire payloads, private reasoning, and provider
thinking signatures are deliberately unavailable in durable analysis context
and trajectory projections. If this pre-call commit fails, the turn fails as
an analysis integrity failure rather than as a provider error.

Historical v1 request artifacts may still be indexed and served as immutable
raw-provider input artifacts. They are not upgraded in place, do not receive
invented semantic fields, and are not equivalent to v2 canonical context
replay.

The older context ledger remains at `context/context-events.jsonl` with
`schema_version: "analysis-context-event/1.0"` and validation by
`schemas/analysis-context-event-v1.schema.json`. For native runs it is a
compatibility projection: each native context event is made durable first and
its native sequence is retained by the projected event. Every compatibility
event records `analysis_id`, monotonic `sequence`, `previous_revision`,
`previous_state_hash`, `next_revision`, `next_state_hash`, and `integrity`
(`verified` or `diagnostic`). Its normative event names are:

- `analysis.started`
- `turn.started`
- `simulator.context.opened`
- `tool.observation.recorded`
- `result.registered`
- `evidence.registered`
- `fact.verified`
- `domain.state.projected`
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
limitations. `answer.submitted` records the controller-owned answer commit,
then `turn.completed` closes the active turn and snapshots consumed and
produced references. After all turns close successfully, `analysis.completed`
finalizes the run; terminal setup, Pi, simulator, empty model-final-text,
controller-submission, or integrity failures record `analysis.failed` when no
active turn remains.

No new turn may begin while `current_turn` is set. Result and evidence
registration requires an active matching turn unless the reducer explicitly
allows a global diagnostic. Replay of `context/context-events.jsonl` must
equal `context/analysis-context.json` and the in-memory snapshot. Before a
completed manifest is published, native replay must also be failure-free and
end with `analysis.completed`. If native replay or capture verification fails,
the manifest remains failed and no event is appended after an invalid native
prefix.

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
`domain.state.projected` applies a strict capability-produced delta to the
active model, operating state, constraints, scenarios, calculations,
capability availability, and artifact index while preserving model revision
and producer-turn provenance.
`tool.failed`, `audit.diagnostic.recorded`, and diagnostic
`limitation.recorded` events preserve failure evidence without inventing an
answer. `limitation.resolved` removes an unresolved limitation by reference.
`answer.submitted` is the authoritative ledger event for an accepted answer.
It is emitted by the controller, not by a model tool call. The event is
appended before `turn.completed` and records the turn binding, accepted answer
artifact path and hash, archived controller draft path, result refs, and
claimed evidence refs. `turn.completed` then archives the accepted answer JSON
path, freezes per-turn ref lineage, and records the answer artifact summary.
`analysis.completed` and `analysis.failed` set terminal status.

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

`trace/events.jsonl` is likewise a compatibility projection for native runs.
It continues to store semantic RPC events for existing reports, while native
event sequences provide authoritative lifecycle links. Streaming token deltas,
reasoning deltas, and repeated message snapshots are excluded from both
persisted surfaces.

Native tool-invocation sidecars are immutable at
`tool-results/<turn_id>/<tool_call_id>.json`. Compatibility observation
documents use the disjoint
`tool-results/<turn_id>/compatibility/<tool_call_id>.json` path and must never
replace or edit the native sidecar.

`analysis_context.changed` and `analysis_context.injected` are trace-only
lifecycle records. They carry the view revision/state hash (and injection path)
for every model injection, but never enter the authoritative context ledger or
change its revision. Tool-derived context events retain their compact RPC
`trace_sequence` in that ledger.

Context projection and integrity diagnostics are deterministic consumers of the
successful tool conversation. A projection failure records a concrete
diagnostic and may leave a semantic record absent, but it does not overwrite an
accepted answer or semantically re-evaluate simulator facts. Simulator failures
and reference integrity failures remain visible and are not relabeled as a
generic execution limitation.

## Typed Domain State

`domain_state` contains these records:

- `model`: active immutable model, revision, source, and element counts.
- `operating_state`: current solved or observed operating-state summary.
- `constraints`: source-bearing voltage, loading, or other bounds.
  `source_kind` is `model`, `user`, `standard`, or `task`; `source_ref`
  identifies its supporting record.
- `scenarios`: isolated changes such as a single-branch outage, including
  parent, status, and result relationships.
- `calculations`: typed power-flow or contingency results, solver status,
  applicability, artifact path, and evidence.
- `capabilities`: capability-family availability with a concrete reason.
- `artifacts`: typed links to complete data retained in the run.

Every record is tied to a model revision and producer turn.
`domain.state.projected` is accepted only in that turn; calculations must
reference an already registered result at the same baseline revision. Opening
another model changes the active projection without erasing history.

Capability availability has five distinct meanings:

- `published`: callable in the current runtime.
- `not_published`: known family with no exposed semantic capability.
- `not_applicable`: published behavior does not apply to the active model,
  scenario, or result.
- `unavailable`: supported behavior currently lacks a runtime prerequisite.
- `failed`: an actual invocation was attempted and failed.

These statuses must not be collapsed into one generic failure label.

## Model-facing Context View

Before every prompt, `grid-agent` writes
`context/analysis-context-view.json` (`analysis-context-view/1.0`) and passes
that bounded view to Pi. The view includes the current revision and state hash,
the active baseline and `active_model`, capability status, sourced constraints,
active scenarios, reusable calculations, the active turn, completed turn
summaries, verified facts grouped by predicate, and unresolved limitations. It
must preserve provenance fields (`result_ref`, `revision_ref`, `evidence_refs`,
`producer_observation`) rather than truncating references. Large simulator
tables are omitted from the view and remain available only through registered
artifacts and follow-on grid tools.

Only calculations whose context and revision match the active `model` are
reusable in the injected view. Stale calculations remain in
`context/analysis-context.json` and their artifacts for replay and audit, but
are not offered as applicable inputs to the next instruction.

## Report Projection

`report.md` is a projection from the finalized context and workspace files.
It is organized for an operator reading one instruction at a time: **question
→ simulator and tool results → model conclusion → execution status and
evidence → integrity diagnostics**. Tool steps are reconstructed from the
recorded start/result trace and are presented with semantic descriptions,
durations, and bounded structured result values before model prose. Evidence
is associated with a turn by its produced and consumed references, because an
evidence artifact can be registered globally while still supporting one
specific answer. The main report links each turn to `turns/<ordinal>/trace.md`;
that page records redacted tool inputs, structured outputs, timing, and links
to the corresponding raw tool-result artifact.
Internal content-addressed references are excluded from reader-facing prose so
that conclusions are not buried under hashes; the accepted original answer
remains linked as an artifact. Tool execution is derived only from recorded
observations and shows the tool purpose, relevant human-readable input, and
compact verified outcome; it does not reproduce hidden model reasoning.
Runtime metadata, baseline, diagnostics, forensic artifact links, and the full
result/evidence/observation reference index appear only in integrity
diagnostic sections or linked artifacts. Report diagnostics may explain missing
or malformed artifacts, but the report must not infer simulator facts absent
from the context.

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
{"capability":"analysis.contingency.n_minus_one.run","arguments":{"context_ref":"context:sha256:...","branch_refs":["asset:line:..."]}}
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

## Held-Out Continuous Flow

A five-turn flow whose wording is absent from the validation question list
demonstrates the general state transitions:

1. Load the registered network and explain one branch endpoint. `context.open`
   sets `model`; topology evidence does not create a calculation.
2. Ask what voltage bounds “this network” defines. The next prompt resolves
   `active_model.context_ref`, calls `model.constraints.describe`, and projects
   model-sourced `constraints`.
3. Run AC flow and report active loss. The capability consumes the active model
   and creates a registered power-flow result plus one `calculations` record.
4. Ask to rank five branches “using that result”. The exact compatible result
   is reused; power flow is not rerun.
5. Ask to outage “the first”. The active context and ranking are reused,
   `scenarios` and a contingency calculation are added, and raw metrics are
   reported with the returned model constraint evaluation.

The Pi process provides language continuity for omitted subjects. The
structured view independently provides authoritative model identity, revision,
constraint sources, and result applicability.
