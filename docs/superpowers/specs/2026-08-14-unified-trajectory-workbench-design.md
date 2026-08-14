# Unified Agent and Business Trajectory Workbench Design

**Status:** Approved design

**Baseline:** Git tag `v0.2` (`dc7a2cf`)

**Golden historical run:** `runs/analysis-20260814T081822Z`

## 1. Purpose

Trajectory and context are first-class product capabilities of `grid-agent`, not debugging residue. A completed static-analysis run must explain both the power-system work and the agent execution that produced it:

- what problem the agent was solving;
- what the agent chose to do and why it declared that choice;
- which model requests and project tools actually ran;
- which authoritative context was available before and after each action;
- what the model actually received in each request;
- which result and evidence artifacts support each submitted claim;
- where retries, failures, limitations, and integrity boundaries occurred.

The project already persists a Pi sidecar, a compact semantic trace, a hashed analysis-context ledger, context snapshots, result and evidence artifacts, accepted answers, turn-level trace pages, and a reader-focused report. These records prove the `v0.2` behavior but form several related timelines rather than one run-wide event source. The next phase introduces one project-native run event spine, independent projections, a legacy importer, a read-only local API, and a high-fidelity trajectory workbench.

DeepSeek Harness is architectural prior art, not a runtime dependency. Its most relevant patterns are:

- one typed append-only session log as the source for replay and presentation;
- a strict distinction between durable events and live coordination;
- independent business projections over the same event window;
- model-visible input reconstructability;
- stable identities, sequence-based pagination, virtualized trajectory rows, request timing, and local inspection;
- refusal to reconstruct when an unknown required event may change semantics.

The project retains its Python runtime, Pi integration, `gridctl` simulator boundary, content-addressed power-system evidence, and exact stdout envelope.

## 2. Goals

1. Define one append-only, typed, hash-chained event stream for native runs.
2. Preserve exact run chronology, causation, scope, provenance, context revision changes, and artifact relationships.
3. Project the same events into independent agent, business, context, and artifact views.
4. Make the business-solving trajectory the default operator experience and expose agent/runtime details by drill-down.
5. Reconstruct the authoritative context and the exact model-visible request input at any supported point.
6. Distinguish observed facts, deterministic derivations, and agent declarations.
7. Import `v0.2` runs without modifying their source files or inventing missing facts.
8. Provide a polished local read-only Web workbench that can later accept durable live events without changing projection semantics.
9. Preserve all current CLI, simulator, evidence, reporting, and validation contracts.

## 3. Non-goals

The first implementation does not provide:

- live event streaming or mid-run control from the browser;
- cross-run statistical comparison or aggregate dashboards;
- manual editing, annotation, deletion, or repair of trajectory events;
- migration or rewriting of historical run directories;
- exposure of hidden model chain-of-thought;
- arbitrary filesystem browsing through the local API;
- replacement of Pi, `gridctl`, pandapower, or the current capability protocol;
- additional grid-analysis capabilities such as DC power flow, OPF, short-circuit, state estimation, or multi-network lifecycle operations.

## 4. Design Principles

### 4.1 One chronology, multiple projections

`run-events.jsonl` owns durable run order and relationships. Agent, business, context, report, and UI models are deterministic projections. A projection cache is disposable and never becomes a competing fact source.

### 4.2 Model-visible means reconstructable

Anything supplied to a model request must be reconstructable from the event stream plus immutable request artifacts. This includes provider/model configuration, system policy, tool schemas, conversational messages, and the bounded analysis-context view.

### 4.3 Facts keep their authority

Numerical and network-specific facts still cross the simulator boundary through `gridctl` using `grid-capability` protocol `1.0` and pandapower `3.4.0`. A trajectory event may point to a result or evidence artifact; it never substitutes for one.

### 4.4 Provenance is explicit

Persisted source kinds are:

- `observed`: emitted from an actual runtime, tool, context, answer, or audit transition;
- `agent-declared`: a bounded statement the model explicitly submitted through a project tool.

`derived` is a projection marker, not a persisted source kind. A derived business node cites the exact source sequences used to produce it.

### 4.5 Missing remains missing

Importers and projections do not infer intent from prose or fabricate timestamps, durations, claims, relationships, or context. Missing historical data is represented as unavailable with source coordinates and a reason.

### 4.6 Durable before visible

An event is appended and fsynced before a projection or future live subscriber can observe it. An artifact is committed and verified before an event may reference it.

### 4.7 Public reasoning, not hidden reasoning

The system records public assistant output, tool behavior, agent-declared decisions, request timing, usage, retries, and failures. It does not persist or expose hidden chain-of-thought. Provider-exposed reasoning summaries remain classified diagnostic sidecar data and are hidden from the business workbench by default.

## 5. Runtime Artifact Layout

Native runs add these paths:

```text
runs/<analysis_id>/
  events/
    run-events.jsonl                 authoritative run event spine
  requests/
    <request_id>/
      input.json                     immutable model-visible request
      response.json                  complete public model response
  projections/
    agent-trajectory.json            rebuildable materialization
    business-trajectory.json         rebuildable materialization
    context-timeline.json            rebuildable materialization
    artifact-index.json              rebuildable materialization
  input/
  output/
  context/
  evidence/
  tool-results/
  turns/
  trace/
  pi/
  manifest.json
  report.md
```

Existing `context/analysis-context.json`, report, answer, result, evidence, tool-result, and Pi artifacts remain supported. During the transition, compatibility projections may continue to write `context/context-events.jsonl` and `trace/events.jsonl`; they are derived compatibility surfaces for native unified runs, not independent authority.

Historical runs remain byte-for-byte unchanged. Their derived import indexes and projection caches live under:

```text
.grid-agent/trajectory-cache/<analysis_id>/
```

## 6. Unified Event Protocol

### 6.1 Envelope

The native event schema version is `grid-run-event/1.0`.

```json
{
  "schema_version": "grid-run-event/1.0",
  "analysis_id": "analysis-20260814T081822Z",
  "sequence": 42,
  "timestamp": "2026-08-14T08:19:12.123456Z",
  "event_type": "tool.completed",
  "previous_event_hash": "sha256:...",
  "event_hash": "sha256:...",
  "scope": {
    "turn_id": "analysis-20260814T081822Z-t007",
    "step_id": "analysis-20260814T081822Z-t007-s001",
    "request_id": "request:...",
    "tool_call_id": "call_00_..."
  },
  "causation": {
    "parent_sequence": 40,
    "correlation_id": "turn:..."
  },
  "source": {
    "kind": "observed",
    "producer": "grid-agent.pi-rpc",
    "integrity": "verified"
  },
  "context": {
    "before_revision": 59,
    "after_revision": 78
  },
  "refs": {
    "consumed": ["context:sha256:..."],
    "produced": ["result:sha256:..."],
    "evidence": ["evidence:sha256:..."]
  },
  "payload": {}
}
```

Required fields are `schema_version`, `analysis_id`, `sequence`, `timestamp`, `event_type`, both hash fields, `scope`, `causation`, `source`, `context`, `refs`, and `payload`. Optional values are omitted inside their containing objects rather than encoded as empty strings. The native `grid-run-event/1.0` recorder always writes a non-null UTC instant. The common replay model permits `timestamp: null` only for a legacy normalized event whose source does not prove a time; that compatibility allowance does not relax the native writer contract.

`scope` is a nested identity chain. An event may omit the lower levels, but it cannot provide a step without a turn, a request without a step, or a tool call without the owning request.

`parent_sequence` identifies the direct cause when one event proves it. `correlation_id` groups a lifecycle whose exact parent may have several concurrent children. Neither field is inferred when the relation is ambiguous.

The `refs` fields contain only registered current-run references. `context.before_revision` and `after_revision` identify the authoritative analysis-context state around the event; no-change events use the same revision on both sides.

### 6.2 Hash chain

Sequence numbers start at `1` and remain contiguous. The first event uses the protocol-defined zero hash as `previous_event_hash`. Each subsequent event repeats the preceding `event_hash`.

`event_hash` is the SHA-256 digest of canonical UTF-8 JSON for the complete event without the `event_hash` member and with a final newline. Canonical JSON sorts object keys, preserves list order, rejects non-finite numbers, and emits no insignificant whitespace.

The hash chain proves event order and content. Each stateful projector separately records its projection revision, last source sequence, and state hash. A valid event chain does not by itself prove that a projection was correctly reduced.

### 6.3 Event families

The initial required vocabulary is:

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

Event payloads are closed, versioned Pydantic models. Plugin-style runtime extension is not required for the first version. A later optional event may carry `ignorable: true` in a compatible envelope revision. A reader encountering an unknown event without that marker refuses trusted reconstruction at that sequence.

### 6.4 Request artifacts

`model.request.started` references an immutable `requests/<request_id>/input.json` containing:

- provider and model configuration;
- rendered system policy and project guides;
- model message history supplied to the request;
- model-facing tool schemas;
- the bounded context view and its revision/state hash;
- the source event sequences used to assemble the request.

`model.response.completed` references `response.json` containing the complete public assistant message, usage, stop status, provider/model provenance, start/completion time, first-token time when observed, and source sidecar coordinates. The main event contains a bounded summary and the artifact digest rather than a second large copy.

Token deltas and hidden reasoning do not enter the main event stream. Provider raw records continue under `pi/` for restricted diagnostics.

## 7. Capture Architecture

### 7.1 Single writer

`RunEventRecorder` is the only native writer of `run-events.jsonl`. Producers submit typed drafts. The recorder:

1. validates payload and scope requirements;
2. checks referenced artifacts and current-run refs;
3. redacts configured secrets and rejects prohibited reasoning fields;
4. assigns the next sequence and timestamp;
5. sets the prior hash and computes the event hash;
6. appends canonical JSON and fsyncs the file;
7. publishes the committed event to projection subscribers.

Recorder failure is a run-integrity failure. The analysis must not continue producing answers after it loses its authoritative history.

### 7.2 Capture points

```text
AnalysisRunner
  ├── analysis / turn / step lifecycle
  ├── Pi RPC adapter
  │     ├── model request / public response
  │     ├── usage and timing
  │     └── retry lifecycle
  ├── project grid-tool adapter
  │     ├── invocation arguments
  │     ├── result or typed failure
  │     └── result and evidence refs
  ├── analysis-context projector
  │     ├── before/after revision
  │     └── immutable request input
  ├── bounded business declaration tool
  └── answer submission and audit
```

Parallel tools receive identities before execution. Their start and settlement events enter the total order when observed. Pairing uses `tool_call_id`; it never relies on adjacent events. A tool-result artifact is atomically persisted before `tool.completed` references it.

### 7.3 Business decision declaration

Pi receives one additional project-defined tool, provisionally named `grid_record_decision`. It is not a simulator capability and cannot register results, facts, or evidence.

Its bounded input is:

```json
{
  "intent": "Determine whether line 17 passes N-1 security checks",
  "decision": "Run the published single-branch contingency capability against the active model",
  "next_action": "Resolve line 17 and execute the contingency",
  "refs": ["context:sha256:..."]
}
```

The tool:

- requires an active turn;
- enforces concise text and bounded reference counts;
- accepts only known current-run refs;
- records `business.decision.declared` with `source.kind = agent-declared`;
- states explicitly that the payload is agent intent, not simulator truth;
- rejects invalid declarations without synthesizing replacements.

Decision declarations are optional for run completion. Their absence creates no inferred intent node.

### 7.4 Structured answer claims

`grid_submit_answer` adds `claims[]`. Each claim contains:

- a concise statement;
- a claim category such as topology, constraint, numerical result, risk judgment, or offline information;
- supporting result refs;
- supporting evidence refs.

Simulator-backed claims must use known, verified current-run refs. Offline informational claims create no simulator evidence. Existing answer-level `result_refs` and `claim_evidence_refs` remain envelope-level integrity declarations; the union of claim refs must be compatible with them.

Claim validation and answer acceptance complete as one validation operation before any claim event is appended. After all refs and envelope declarations validate, claim events carrying a shared `submission_id` emit immediately before the matching `answer.submitted`. A business projector treats them as accepted claims only when that terminal event exists; a crash between records leaves an explicitly incomplete submission rather than an accepted claim. A rejected draft may emit `answer.rejected` with a bounded reason, but none of its proposed claims enter the authoritative business trajectory. A submitted answer remains an immutable artifact. The system never parses answer prose to manufacture claim records.

## 8. Projection Architecture

All projectors are deterministic pure reducers over an event prefix. Given the same validated events and registered artifacts, they produce byte-identical canonical output.

### 8.1 Agent trajectory

The agent projection organizes:

```text
Analysis
  Turn
    Step
      ModelRequest
        Retry attempts
        AssistantResponse
        ToolCall tree
```

It retains stable ids, source sequences, request timing, TTFT, provider/model, token usage, retry state, public input/output artifact refs, tool arguments, typed results, errors, and nested calls. An open lifecycle stays explicitly running. A closed boundary with no settlement marks it interrupted; the projector does not invent a duration for a still-open event.

### 8.2 Business trajectory

The business projection makes each instruction a problem and assembles ordered nodes:

- agent-declared decision;
- observed model or tool action relevant to the domain workflow;
- derived context change;
- agent-declared claim;
- observed answer, evidence, limitation, or audit outcome.

Derived nodes cite the source sequences and projection rule that produced them. Tool names are rendered through project-owned semantic descriptions. A business node never asserts a numerical result not present in a verified simulator artifact.

### 8.3 Context timeline

The context projection supports event-level time travel. For any supported source sequence it returns:

1. the authoritative domain state before the event;
2. the typed state delta caused by the event;
3. the authoritative domain state after the event;
4. the next model-visible request input when one exists;
5. provenance paths from state records to source events and artifacts.

The reducer uses periodic checkpoints plus event deltas. Checkpoints are caches; replay from the authoritative event prefix remains the correctness path. Each checkpoint records the source sequence, context revision, state hash, and projection schema version.

### 8.4 Artifact index

The artifact projection maps each registered ref to:

- artifact kind and safe run-relative path;
- digest and verification status;
- producing event;
- consuming events;
- associated turn, step, request, tool call, result, evidence, and claim ids.

Only indexed artifacts are retrievable through the local API.

### 8.5 Materialization failure

A projection failure does not rewrite or append compensating domain facts. The UI reports the last successfully projected sequence and the projection error. Rebuilding from the event spine is the recovery mechanism. Native run execution may continue when a non-authoritative presentation projection fails, while recorder, artifact-integrity, simulator, and answer-integrity failures retain their current terminal behavior.

## 9. Historical `v0.2` Import

The first importer targets the exact layout produced by tag `v0.2` and is validated against `runs/analysis-20260814T081822Z`.

It reads, without modifying:

- `manifest.json` and copied instructions;
- `context/context-events.jsonl` and `analysis-context.json`;
- `trace/events.jsonl`;
- the Pi JSONL sidecar;
- turn answers, drafts, audits, and trace pages;
- tool-result, result, and evidence artifacts;
- the final report.

The importer builds a deterministic merged partial order:

1. context-ledger order governs domain transitions;
2. semantic-trace order governs observed Pi and tool transitions;
3. `trace_sequence` creates proven cross-stream edges;
4. turn ids and lifecycle boundaries constrain placement;
5. ambiguous ties use a documented stable source-rank and source sequence, without claiming a wall-clock relationship.

Normalized events retain source coordinates for every imported record. `source.kind` remains `observed`; `source.producer` identifies `legacy-v0.2-importer` and the originating file/sequence. A normalized legacy timestamp is null when no source proves it. The importer computes a separate deterministic normalization hash chain for cache corruption detection; it is labeled as importer integrity and never presented as proof that the original independent files had one total order. Original source digests and coordinates remain attached to every normalized event.

The importer does not parse answer prose into decisions or claims. Legacy answers retain their answer-level refs. Missing request inputs, token timings, or structured declarations are represented as unavailable. Import output is held in memory or cached under `.grid-agent/trajectory-cache/`; source runs remain byte-for-byte unchanged.

## 10. Read-only Local API

The entry point is:

```sh
grid-agent trajectory serve
# Makefile convenience target
make trajectory
```

The server binds to loopback by default and scans the configured `runs/` root. Initial resources are:

```text
GET /api/runs
GET /api/runs/{analysis_id}
GET /api/runs/{analysis_id}/business?cursor=...
GET /api/runs/{analysis_id}/agent?cursor=...
GET /api/runs/{analysis_id}/context?at_sequence=...
GET /api/runs/{analysis_id}/artifacts/{ref}
```

Cursors encode stable source sequence positions plus projection version. They do not expose mutable array indexes. Invalid, stale, foreign-run, or tampered cursors receive typed errors.

The initial tail response is bounded. Older pages prepend by sequence without changing existing row identities. Optional JSONL byte-offset indexes, context checkpoints, and search indexes are stored only in `.grid-agent/trajectory-cache/`.

A later streaming endpoint may deliver committed events after a supplied sequence. It must publish only after durable append and use the same event and projection semantics as historical replay.

## 11. Workbench UI

### 11.1 Information architecture

The approved workbench has four persistent regions:

- left run explorer with status, filters, and saved views;
- top run header and overview timeline;
- central view tabs for Business, Agent, Context, and Evidence;
- right inspector for the selected node's identity, input, output, timing, context delta, refs, and artifacts.

Business is the default view. It serves power-system analysts first. Agent/runtime details serve developers and auditors through drill-down rather than dominating the landing page.

### 11.2 Business view

Each turn renders as a problem with a chronological solving journey. Node chrome clearly labels `observed`, `derived`, or `agent-declared` using text and icons as well as color. Selecting a node updates the context/evidence inspector without navigating away.

### 11.3 Agent view

The Agent tab provides a Harness-quality turn-aware ledger and timeline:

- thick turn boundaries and compact step markers;
- request numbering and cumulative usage;
- assistant TTFT, decoding duration, and completion timing;
- tool start/result pairing and nested calls;
- retry and interruption states;
- selectable Input, Output, Timing, schema, and artifact details;
- search, turn/assistant folding, interval focus, and tail positioning;
- virtualized rows and stable selection across prepended pages.

### 11.4 Context view

The Context tab lets the operator select an event sequence and compare before state, typed delta, and after state. It also exposes the immutable request input for the model request associated with that point. Stale calculations remain visible historically but are labeled inapplicable when the active model revision differs.

### 11.5 Evidence view

The Evidence tab starts with an accessible relationship tree/table rather than requiring a graph. Claims, decisions, results, evidence, scenarios, tools, and model revisions are navigable in both directions. A later graph presentation can consume the same artifact projection.

### 11.6 Interaction and visual quality

The implementation must meet or exceed the DeepSeek Harness trajectory UI in information hierarchy, density, polish, and state handling. Required behavior includes:

- virtualized rendering with semantic row keys;
- sequence-cursor history pagination;
- search and fold controls;
- stable selection, focus, and scroll across pagination and projection updates;
- dedicated loading, empty, partial, corrupt, and unsupported states;
- keyboard navigation and visible focus;
- ARIA labels and indexes for virtualized content;
- provenance indicators that do not rely on color alone;
- dark and light themes using shared design tokens;
- responsive inspector behavior for narrower screens;
- screenshot-based visual regression at representative viewport sizes.

## 12. Failure and Compatibility Semantics

### 12.1 Fail-closed replay

On a sequence gap, invalid envelope, hash mismatch, invalid scope, unknown required event, or impossible state transition, trusted replay stops at the last valid sequence. The UI may show raw diagnostic metadata after the boundary only in an explicitly untrusted section; it does not merge those records into business conclusions.

An unknown event may be skipped only when its envelope explicitly marks it ignorable under a compatible schema. Skips appear as diagnostics.

### 12.2 Partial and interrupted runs

The workbench renders every durable fact in a partial run. Open requests and tools remain running until a stored boundary proves interruption or settlement. The UI does not fabricate live elapsed durations for a historical lifecycle with no completion time.

### 12.3 Legacy limitations

The importer reports missing fields at their consumer surface. It does not fail an otherwise valid historical run merely because the newer native protocol captures more data. It does fail closed when the old source's own integrity contracts do not verify.

### 12.4 Schema evolution

Compatible additions are optional fields with defined absence semantics. Incompatible envelope or event-payload changes require a new schema version and an explicit reader/importer. Readers refuse unknown required semantics rather than silently resuming a truncated trajectory.

## 13. Security and Trust Boundaries

- The server is read-only and binds to `127.0.0.1` unless the operator explicitly configures another interface.
- Run ids resolve through discovered manifests, never direct path concatenation from request input.
- Artifact access requires an entry in the artifact projection and a verified safe run-relative path.
- Directory traversal, absolute paths, escaping symlinks, device files, and unregistered files are rejected.
- API responses use fixed content types and browser security headers. Rendered Markdown does not execute raw HTML or scripts.
- Secret redaction occurs before native event append. The browser never receives provider credentials or process environments.
- Pi raw sidecars are not generic downloadable files. Any future raw-event view requires a project-owned redacted projection.
- The Web application cannot invoke grid tools, mutate runs, answer questions, or alter evidence.
- Nothing in the UI changes the model capability boundary: Pi still receives only project-defined grid tools, `grid_guide_open`, `grid_record_decision`, and `grid_submit_answer`.

## 14. Performance Model

The UI loads the current tail first and requests older pages on demand. The server does not parse and return an entire large log for the initial view.

Required bounded behavior:

- a page contains at most 500 projected records and at most 2 MiB of JSON before transport encoding;
- the DOM mounts only the visible row window plus bounded overscan;
- prepend preserves existing row identities and selection;
- context reconstruction uses the nearest validated checkpoint and subsequent deltas;
- search indexing is incremental and may complete after the initial tail is interactive;
- a synthetic 100,000-event run opens at its tail without rendering or transmitting all records.

Exact latency budgets belong in the implementation plan after measuring the selected Python server and browser stack on the project's supported development environment.

## 15. Testing Strategy

### 15.1 Protocol and recorder

- schema validation for every event payload;
- contiguous sequence and hash-chain verification;
- canonical JSON and deterministic digest tests;
- scope and causation constraints;
- secret and prohibited-reasoning rejection;
- artifact-before-event enforcement;
- fsync/write failure behavior;
- concurrent producer ordering through one recorder.

### 15.2 Projectors

- unit tests for every event transition;
- property tests for replay determinism and prefix equivalence;
- idempotent materialization and cache deletion/rebuild;
- context before/delta/after correctness;
- source-sequence provenance for every derived business node;
- no numerical business fact without a verified simulator source;
- interrupted lifecycle and unknown-event behavior.

### 15.3 Legacy importer

- golden import of `runs/analysis-20260814T081822Z`;
- byte-for-byte proof that source files are unchanged;
- deterministic normalized output across repeated imports;
- all 9 turns and all 36 observed tool starts/results represented;
- context `trace_sequence` relationships preserved;
- Q7 result/evidence lineage preserved;
- missing structured decisions, claims, and request inputs labeled unavailable;
- corrupted ledger, trace, artifact, and hash cases fail at the correct boundary.

### 15.4 API and security

- cursor pagination and invalid cursor errors;
- loopback default;
- run discovery and typed unavailable states;
- artifact allowlisting, traversal, absolute path, and symlink escape rejection;
- fixed content types, CSP, and Markdown sanitization;
- no mutation routes.

### 15.5 UI

- component tests for every node source kind and lifecycle state;
- Playwright flows for run selection, pagination, search, folding, timeline focus, context time travel, and artifact drill-down;
- keyboard-only operation and ARIA checks;
- visual regression for dark/light, wide/narrow, loading, partial, corrupt, and unsupported states;
- stable row selection and scroll after prepend;
- 100,000-event virtualization fixture;
- approved workbench mockup used as the visual hierarchy baseline.

### 15.6 Existing project gates

The implementation must continue to pass:

```sh
make doctor
make test
make test-e2e
make validate
```

Provider validation remains optional and billed. The existing `runs/<question_id>/` evidence rules and single stdout JSON object contract remain unchanged.

## 16. Acceptance Criteria

The first release is accepted when:

1. A native run writes a valid hash-chained `grid-run-event/1.0` log.
2. Agent, business, context, and artifact projections rebuild from that log without reading mutable projection state as authority.
3. Every native model request references an immutable artifact representing its actual model-visible input.
4. The business view distinguishes observed, derived, and agent-declared nodes.
5. Agent decisions are explicit bounded declarations; missing intent is never inferred.
6. Submitted simulator-backed claims have claim-level result/evidence lineage.
7. The `v0.2` golden run imports without source modification and displays all 9 questions.
8. Its 36 observed tool calls pair correctly in the Agent trajectory.
9. Q7 drills from the failed N-1 judgment to the exact context revision, contingency result, and evidence.
10. Historical data absent from `v0.2` is labeled unavailable instead of synthesized.
11. The local workbench implements the approved four-region UI and high-fidelity interaction states.
12. A 100,000-event fixture remains paginated and virtualized.
13. Corruption and unknown required events stop trusted replay at the last valid sequence.
14. The local API cannot read outside registered run artifacts or mutate a run.
15. Existing CLI, simulator, report, validation, stdout, and evidence contracts do not regress.

## 17. Delivery Boundaries

Implementation planning should preserve these separable packages of work:

1. unified event schema, recorder, hashing, and request artifacts;
2. native capture adapters and structured decision/claim contracts;
3. pure projectors and materialized caches;
4. deterministic `v0.2` importer;
5. read-only local API and security boundary;
6. workbench shell and Business view;
7. Agent, Context, and Evidence views;
8. performance, accessibility, visual regression, and full integration gates.

The implementation plan may split these into independently verified waves, but it must not build the UI directly on the old collection of files or make a projection cache authoritative.

## 18. Approved Decisions

- Implement project-native trajectory infrastructure; do not depend on DeepSeek Harness at runtime.
- Deliver historical replay before live streaming.
- Use the business-solving trajectory as the default UI and expose agent/runtime detail through drill-down.
- Do not store or display hidden chain-of-thought.
- Use `runs/analysis-20260814T081822Z` as the golden legacy replay fixture.
- Serve a local read-only Web workbench through `grid-agent trajectory serve` and `make trajectory`.
- Treat event-level context time travel as a first-release requirement.
- Persist observed and agent-declared sources; derive business nodes through pure projections.
- Use one unified append-only run event spine while retaining large artifacts and Pi diagnostics as sidecars.
- Match or exceed the information density, interaction quality, accessibility, and polish of DeepSeek Harness's trajectory UI.
