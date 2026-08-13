# Continuous Analysis Context Design

## Purpose

Replace the current batch-oriented `report` execution model with a one-shot, continuous `analysis` run. One Pi/LLM process executes an ordered instruction set, later instructions can reuse verified results from earlier instructions, and the run produces one self-contained analysis directory and one final report.

Make the analysis execution context a first-class, structured control-plane artifact. It must show which frozen simulator baseline, verified facts, results, evidence, failures, and prior-turn outputs are available at every point in the trajectory. It must be deterministic, replayable, inspectable, and derived from project-controlled events rather than from model-authored summaries.

## Problem Statement

The existing `grid-agent report` command launches a new `grid-agent run` subprocess for every question. Each subprocess has a separate Pi process, session, workspace, evidence store, and conversation, so later questions cannot reliably reuse earlier results.

The existing report also renders a `SimulationContext` under every question. That object describes the same immutable network baseline each time: model, source, engine version, context reference, semantic fingerprint, and element counts. Repeating it does not describe the changing state of an analysis and makes a static simulator baseline look like a dynamic task context.

Finally, the default Pi trace stores streaming deltas and repeated message snapshots. This makes practical runs hundreds of megabytes without improving result provenance or control.

## Goals

- Execute an ordered instruction set in one Pi process and one conversation.
- Preserve the stdout envelope contract: exactly one JSON object containing `question_id` and `answer_output`; all progress and diagnostics go to stderr.
- Keep all inputs, per-turn outputs, reports, traces, results, and evidence beneath one analysis directory.
- Separate conversation history, immutable simulator baselines, and authoritative analysis execution state.
- Maintain an append-only context event ledger and a deterministic materialized context snapshot.
- Make context changes visible in the execution trace and final report.
- Let later instructions discover and reuse verified prior results without trusting model memory alone.
- Keep numerical and network-specific facts behind the `gridctl` `grid-capability` 1.0 boundary.
- Preserve submitted answers when answer audit reports invalid or misclassified references.
- Reduce standard trace volume by storing semantic events instead of streaming snapshots.
- Keep the context semantics, JSON Schemas, implementation, tests, and report rendering aligned through a maintained architecture contract.

## Non-goals

- Named sessions, switching between sessions, pause/resume, or continuing an analysis in a later process.
- Cross-run result reuse.
- Concurrent instruction execution.
- Arbitrary model-side file access, shell access, Python execution, or raw pandapower access.
- Allowing the LLM to author or mutate authoritative context state.
- Inferring hidden dependencies between instructions with a planner.
- Treating audit diagnostics as a final correctness verdict.
- Persisting hidden chain-of-thought or raw streaming traces by default.
- Mutating a registered network or introducing dynamic simulation.

## Chosen Approach

Use an append-only event ledger plus a deterministic materialized view.

Two simpler alternatives are rejected:

1. **Conversation-only continuity.** Keeping one Pi process gives the model conversational memory, but chat history is not a typed, validated, replayable record of simulator state. It cannot serve as the primary diagnostic or trust boundary.
2. **Mutable context JSON only.** A single snapshot is easy to read but cannot explain how state changed, distinguish corruption from an incomplete update, or reconstruct the state after a crash.

The chosen design records validated semantic changes in `context/context-events.jsonl`. A pure reducer materializes `context/analysis-context.json`. Replaying the ledger must produce the same canonical snapshot and state hash.

## Terminology and Authority

### Conversation context

The Pi session contains user instructions, assistant messages, and tool exchanges. It provides language continuity but is not authoritative for simulator facts or result availability.

### Simulator baseline

A simulator baseline is an immutable, gridctl-owned network snapshot identified by:

- `context_ref`;
- `revision_ref`;
- registered model ID and source;
- engine name and pinned version;
- semantic model digest and element counts.

The baseline is authoritative for the network revision. In v1, only one baseline is active at a time. Opening another valid registered model changes the active baseline while preserving prior baseline records and their result associations.

### Analysis execution context

The analysis execution context is the grid-agent-owned projection of the run's verified state. It records the active simulator baseline, turns, observations, results, evidence, verified facts, dependencies, diagnostics, and unresolved limitations.

The context may copy compact facts from verified gridctl results or evidence, but every copied network or numerical fact must retain its source reference and producer event. It may never turn model prose into a verified fact.

### Observation, result, and evidence

- An **observation** is a normalized tool outcome, such as a topology lookup or a branch ranking. It records inputs, compact output, and consumed references.
- A **result** is a content-addressed simulator result artifact identified by `result:sha256:...`.
- **Evidence** is a content-addressed claim-support artifact identified by `evidence:sha256:...`.

A capability such as branch ranking may consume and return an existing `result_ref` without creating a new result artifact. The context therefore records the ranking as an observation that consumes a result, not as a second result.

## CLI Contract

### Canonical command

The canonical interface becomes:

```sh
grid-agent analysis \
  --instructions validation/questions/task.md.txt \
  [--artifact-root runs] \
  [--provider PROVIDER] \
  [--model MODEL]
```

`make analysis` invokes this command. `make report` remains a documented compatibility alias during the migration and invokes the same analysis path; it does not retain the old subprocess-per-question behavior.

The command creates an `analysis-<UTC timestamp>` directory beneath the artifact root. It does not accept independent report and JSONL destinations because that would violate the self-contained-run invariant.

The input file is interpreted as an ordered instruction set. Blank lines and comment lines retain the current parsing behavior. Per-turn IDs use `<analysis-id>-tNNN`.

### stdout and stderr

Progress, checkpoints, tool activity, and diagnostics go to stderr.

On normal completion, stdout contains exactly one envelope:

```json
{"question_id":"analysis-20260814T120000Z","answer_output":"runs/analysis-20260814T120000Z/report.md"}
```

`answer_output` is the project-relative path to the completed analysis report. Per-turn answer envelopes are stored in `output/answers.jsonl` and are not streamed to stdout.

On an execution-ending failure, stdout still contains exactly one envelope with an execution-limitation message, while stderr contains the diagnostic. Any completed forensic artifacts remain in the analysis directory.

## Analysis Directory

One invocation owns one directory:

```text
runs/analysis-20260814T120000Z/
├── manifest.json
├── input/
│   └── instructions.md.txt
├── output/
│   └── answers.jsonl
├── report.md
├── context/
│   ├── analysis-context.json
│   └── context-events.jsonl
├── trace/
│   └── events.jsonl
├── turns/
│   ├── 001/
│   │   ├── instruction.json
│   │   ├── answer.json
│   │   ├── answer-draft.json
│   │   └── answer-audit.json
│   └── ...
├── evidence/
│   ├── contexts/
│   ├── network-facts/
│   ├── analysis/
│   └── results/
├── tool-results/
├── bin/
└── pi/
```

The controller copies the instruction file before starting Pi and records the source path and SHA-256 digest in `manifest.json` and the initial context event. Reports refer to the copied input, so a later edit to the source file cannot change the meaning of a completed run.

Files that are incrementally updated use durable append or atomic temporary-file replacement. The implementation does not migrate or delete historical `runs/` data or user-owned `var/` data.

## Runtime Architecture

### Analysis runner

The analysis runner owns orchestration:

1. Resolve provider and runtime configuration once.
2. Create one analysis workspace and install one workspace-local `gridctl` launcher.
3. Materialize one tool catalog and guide index.
4. Start one Pi RPC process and one Pi session directory.
5. Execute instructions sequentially with repeated `prompt_and_wait` calls.
6. Finalize each turn before sending the next instruction.
7. Stop Pi and finalize the context, manifest, JSONL, and report.

The runner does not call the single-question `grid-agent run` command as a subprocess.

### Turn controller

Each turn has an explicit controller-owned ID and unpredictable nonce. Before prompting Pi, the controller atomically writes an active-turn control record and clears the active answer-draft path.

`grid_submit_answer` continues to expose no filesystem capability to the model. The extension reads the controller-owned active-turn record, binds the submitted draft to the turn ID and nonce, and writes it atomically. After `agent_end`, the controller accepts only a structurally valid draft whose ID and nonce match the active turn, then archives it beneath `turns/NNN/`.

This prevents an answer left by an earlier turn from being mistaken for the current answer. If a turn submits more than once, the last structurally valid submission bound to the active nonce is authoritative; all submissions remain visible in the semantic trace.

### Context tracker

The context tracker consumes normalized domain-tool completion events from the Pi RPC stream. For every event it:

1. Validates the canonical event shape.
2. Resolves and verifies any content-addressed context, result, or evidence artifacts available in the current analysis workspace.
3. Builds one or more compact context events containing references, provenance, and state deltas.
4. Durably appends each event in order.
5. Applies the pure reducer after each append.
6. Atomically replaces the materialized snapshot.
7. Emits `analysis_context.changed` semantic trace events with the before/after revisions and state hashes.

Direct tool output remains available to the model within the current turn. Before the next turn starts, the runner waits until all preceding tool events and the turn-finalization event have been committed.

### Context view for the agent

The model must not depend on conversational recall alone. Before each instruction, the runner injects a bounded, controller-generated context view containing:

- active simulator baseline;
- completed-turn status and answer summaries;
- reusable verified result references and their types;
- verified facts relevant to prior work;
- unresolved limitations;
- current context revision and state hash.

The view is explicitly labeled as controller-generated read-only state and is recorded as `analysis_context.injected` in the semantic trace.

A project-defined read-only tool, `grid_analysis_context_get`, exposes the same bounded context view on demand. It does not provide arbitrary file access and does not create simulator evidence. Numerical data returned by this tool is only an index of already verified gridctl-derived facts with their original references.

## AnalysisContext v1

The authoritative JSON Schema is stored at `schemas/analysis-context-v1.schema.json`. The snapshot has these top-level fields:

```json
{
  "schema_version": "analysis-context/1.0",
  "analysis_id": "analysis-20260814T120000Z",
  "revision": 17,
  "state_hash": "sha256:<canonical-state-digest>",
  "status": "running",
  "input": {},
  "runtime": {},
  "baselines": {},
  "active_context_ref": null,
  "current_turn": null,
  "turns": [],
  "observations": {},
  "results": {},
  "evidence": {},
  "verified_facts": {},
  "diagnostics": [],
  "unresolved_limitations": []
}
```

### Identity and revision

- `schema_version` is fixed to `analysis-context/1.0` for this implementation.
- `revision` starts at zero and increments once for every accepted context event.
- `state_hash` is calculated from canonical JSON of the complete state excluding the `state_hash` field itself.
- `status` is one of `initializing`, `running`, `completed`, or `failed`.

### Input and runtime

`input` records the copied instruction path, original source path, SHA-256 digest, and instruction count. `runtime` records provider, model, request limits, grid-capability protocol version, gridctl identity, pandapower version, and relevant versioned policy identifiers.

Secrets, API keys, authentication documents, and environment-variable values are excluded.

### Baselines

`baselines` is keyed by `context_ref`. Each entry records:

- `context_ref` and `revision_ref`;
- model ID, source, engine, and engine version;
- model semantic digest and element counts;
- the opening turn and producer event;
- integrity status and local context-artifact reference.

Every verified observation, result, evidence record, and numerical fact must identify both its `context_ref` and `revision_ref` when the underlying gridctl contract supplies them. A mismatched pair is never admitted to verified state.

### Turns

`current_turn` records the active ID, ordinal, instruction digest, nonce digest, start time, start revision, and status. Raw nonces are not persisted in the final context snapshot.

Each completed turn records:

- instruction ID, text, and digest;
- start and end context revisions;
- status: `success`, `limited`, or `failed`;
- consumed observation, result, and evidence references;
- produced observation, result, evidence, and fact identifiers;
- answer path and answer digest;
- audit diagnostic IDs;
- duration and error category, when present.

Turn consumption is based on actual tool inputs and submitted claim references, not on inferred semantic dependencies.

### Observations

`observations` is keyed by a run-local observation ID. Each entry records:

- capability and success status;
- producer turn and semantic trace event;
- compact normalized inputs and output summary;
- context and revision references, if applicable;
- consumed and produced content references;
- integrity status;
- a pointer to a persisted full tool result when one exists.

Large branch tables, contingency scenario arrays, and raw datasets are not copied into the context snapshot.

### Results and evidence

`results` is keyed by verified `result_ref`. Each entry records result type, capability, baseline references, solver profile, convergence or aggregate status, producer turn, evidence references, dependency references, and local artifact path.

`evidence` is keyed by verified `evidence_ref`. Each entry records evidence type, capability, baseline references, linked result, producer turn, integrity status, and local artifact path.

References are admitted as verified only after their prefix, digest, document shape, document self-reference, current-analysis location, and context linkage have passed shared content-integrity primitives. Answer auditing reuses those primitives and separately checks whether submitted claim references adequately link to declared results. Context admission does not depend on a later answer submission. Invalid references remain in the originating observation and create diagnostics, but they are not placed in the verified registries.

### Verified facts

`verified_facts` contains compact reusable claims projected from verified gridctl tool results or evidence documents. Each fact records:

- subject and predicate;
- typed value and unit, when applicable;
- baseline references;
- evidence or result source;
- producer observation and turn.

The first implementation supports an explicit allowlist of projections needed by current capabilities, including topology endpoints, convergence status, total active loss, ranking entries, contingency status, maximum loading, and violation counts. Unknown fields remain in full tool-result artifacts and are not promoted automatically.

### Diagnostics and limitations

Diagnostics have a stable ID, category, severity, producer turn/event, finding, impact, remediation, and affected references. Audit diagnostics and execution diagnostics use the same display structure but retain distinct categories.

`unresolved_limitations` contains active conditions that subsequent turns must see, such as non-convergence, an unavailable result, incomplete contingency coverage, or a failed prior turn. A later verified event may resolve a limitation, but the original event remains in the ledger.

## Context Event Ledger

The authoritative event schema is stored at `schemas/analysis-context-event-v1.schema.json`.

Every line contains one JSON object with:

- schema version and event type;
- analysis ID and monotonically increasing sequence;
- timestamp and turn ID;
- producer trace event and capability;
- previous revision/hash;
- normalized payload or state delta;
- next revision/hash;
- integrity outcome.

Required event types for v1 are:

- `analysis.started`;
- `turn.started`;
- `simulator.context.opened`;
- `tool.observation.recorded`;
- `result.registered`;
- `evidence.registered`;
- `fact.verified`;
- `tool.failed`;
- `answer.submitted`;
- `audit.diagnostic.recorded`;
- `limitation.recorded` and `limitation.resolved`;
- `turn.completed`;
- `analysis.completed` or `analysis.failed`.

An event is appended and flushed before its resulting snapshot is atomically replaced. If the process stops between those operations, replaying the ledger reconstructs the latest committed state. This replay capability supports diagnosis and report verification; it does not expose a user-facing resume feature.

## Cross-turn Data Flow

For an ordered instruction sequence:

1. Turn 1 opens the model. The tracker verifies and registers the simulator baseline.
2. A power-flow call creates result `R1` and evidence `E1`. The tracker records their baseline, solver profile, convergence state, and provenance.
3. Turn 1 submits an answer claiming `E1`; its consumed and produced references are finalized.
4. Before turn 2, the injected context view lists `R1` as reusable verified state.
5. Turn 2 calls branch ranking with `R1`. The tracker creates observation `O2` with `consumes: [R1]`; it does not fabricate a new result.
6. Turn 3 can use `R1` and verified facts projected from `O2` to select contingency scope. Its N-1 call creates aggregate result `R3` and scenario evidence tied to the same baseline.

The final context and report therefore expose the concrete dependency chain rather than merely showing that the questions shared a chat session.

## Reporting

The final `report.md` contains:

1. Analysis summary and completion status.
2. Input, provider, model, protocol, and runtime information.
3. One global **Simulator Baseline** section per opened baseline.
4. A global **Analysis Execution Context** section showing final revision/hash, registered results, evidence coverage, unresolved limitations, and diagnostics.
5. A result/evidence dependency table.
6. An ordered instruction timeline. Each instruction shows:
   - answer;
   - status and duration;
   - context revision before and after;
   - reused prior results and evidence;
   - new observations, results, evidence, and verified facts;
   - actual domain-tool steps;
   - audit and execution diagnostics.
7. A forensic artifact index linking the context snapshot, event ledger, semantic trace, per-turn data, results, and representative evidence.

The report does not repeat the same baseline under every turn. It shows baseline changes only when the active `context_ref` changes and otherwise shows the turn-specific context delta.

Markdown is a readable projection, not an authority source. The context snapshot, ledger, content-addressed artifacts, and JSONL envelopes remain machine-readable sources.

The report is checkpointed atomically after each finalized turn for operator visibility. Only the final report is announced on stdout.

## Answer and Audit Semantics

The per-turn `answer_output` written to `output/answers.jsonl`, `turns/NNN/answer.json`, and the Markdown answer section must be byte-for-byte the submitted answer text, subject only to JSON encoding or Markdown placement. The report must not silently replace it with a different conclusion.

Answer audit remains advisory:

- malformed, missing, foreign, or misclassified references produce structured diagnostics;
- diagnostics do not mutate the answer text;
- diagnostics do not turn a completed turn into an execution failure solely because evidence claims are questionable;
- invalid references are excluded from reusable verified context.

A missing or malformed current-turn answer draft is an execution failure because no structurally usable submitted answer exists.

There is one separate hard integrity boundary: if a canonical successful gridctl response points to a content-addressed artifact that is missing, digest-invalid, self-inconsistent, or linked to a mismatched simulator revision, the simulator trust boundary is compromised. The context records `analysis.failed`, the runner stops before issuing another instruction, and the already submitted answers remain preserved. This condition is not an answer-audit verdict.

## Error Handling

### Non-terminal conditions

The analysis continues when Pi remains usable and the simulator trust boundary is intact, including:

- a normal gridctl capability error;
- AC non-convergence with persisted diagnostic evidence;
- an instruction that produces a limited answer;
- a missing answer submission for one turn;
- answer-audit warnings or errors;
- an invalid model-supplied reference that was not asserted by gridctl as a successful artifact.

These conditions create diagnostics or unresolved limitations visible to subsequent turns.

### Terminal conditions

The runner stops issuing instructions when:

- the Pi RPC process exits or its protocol becomes unusable;
- provider failure prevents the session from continuing;
- the analysis workspace cannot durably persist authoritative state;
- a successful gridctl response fails simulator-artifact integrity verification;
- context ledger replay disagrees with the materialized snapshot during finalization.

The manifest and context status become `failed`, stderr explains the failure, and stdout retains the single-envelope contract.

## Trace Policy

`trace/events.jsonl` is a semantic operational trace. By default it records:

- analysis and turn boundaries;
- prompt acknowledgement;
- complete final assistant messages when available, excluding reasoning streams;
- tool start and canonical tool result;
- answer submissions;
- context injection and context revision changes;
- diagnostics and runtime errors.

It does not persist token-level `text_delta`, reasoning deltas, or repeated growing `message_update` snapshots. Hidden chain-of-thought is never persisted.

If a future explicit debug option stores raw provider events, they must go to a separate `trace/raw-events.jsonl`, must not be used to construct reports or authoritative context, and must remain disabled by default. That debug option is not required for the initial implementation.

## Maintained Architecture Contract

The implementation adds `docs/architecture/analysis-context.md` as the long-lived semantic contract. It documents:

- ownership boundaries among grid-agent, the Pi extension, and gridctl;
- state fields and lifecycle;
- event-to-state reduction rules;
- integrity and failure invariants;
- context injection rules;
- report mappings;
- schema versioning and compatibility rules;
- worked examples for topology, AC power flow, ranking, and N-1 analysis.

The two JSON Schemas are normative for serialization. The architecture document is normative for semantics. Generated examples or field tables in documentation must be checked by contract tests so implementation changes cannot silently drift from the documented context model.

## Component Boundaries

The implementation should keep these responsibilities separate:

- `analysis.runner`: lifecycle, sequential prompts, finalization, and CLI outcome.
- `analysis.turns`: active-turn identity, answer-draft isolation, and per-turn archival.
- `analysis.context.models`: typed snapshot and event models.
- `analysis.context.reducer`: pure event-to-state transition logic.
- `analysis.context.store`: durable ledger append, atomic snapshot, replay, and hashing.
- `analysis.context.projector`: canonical tool-result validation and compact fact projection.
- `analysis.context.view`: bounded model-facing context view.
- `analysis.reporting`: Markdown and JSONL projections from finalized context and turn artifacts.

The exact module names may follow existing package conventions, but the reducer, persistence, projection, and rendering responsibilities must not collapse into the CLI command body.

Shared content-reference verification should be extracted from the current answer-audit path so answer auditing and context admission apply identical digest and linkage rules without duplicating policy.

## Testing Strategy

### Schema and reducer tests

- Validate initial, running, completed, and failed snapshots against the JSON Schema.
- Validate every required event type.
- Assert deterministic state hashes for canonical input.
- Replay a ledger and compare the rebuilt snapshot byte-for-byte with the materialized snapshot.
- Reject sequence gaps, previous-hash mismatches, invalid state transitions, and baseline mismatches.

### Projection and integrity tests

- Register valid context, result, and evidence documents.
- Keep ranking as a result-consuming observation rather than a newly produced result.
- Promote only allowlisted, source-linked facts.
- Exclude missing, tampered, foreign, or mismatched artifacts from verified registries.
- Distinguish answer-reference diagnostics from simulator-boundary integrity failure.

### Turn and runtime tests

- Send several prompts through one fake Pi RPC process and prove the process/session is reused.
- Verify a later prompt receives the finalized prior context view.
- Reject stale answer drafts using the turn ID and nonce.
- Continue after a non-terminal turn failure and expose its limitation to the next turn.
- Stop on Pi death or simulator-artifact integrity failure.

### Report and layout tests

- Create every artifact beneath one analysis directory.
- Copy and hash the instruction source.
- Write incremental per-turn JSONL envelopes and report checkpoints.
- Render the simulator baseline once and turn-specific context revisions/deltas per instruction.
- Show reused and newly produced references accurately.
- Preserve submitted answers despite audit diagnostics.
- Keep progress on stderr and emit exactly one stdout envelope.

### Trace tests

- Preserve canonical tool and context events.
- Exclude text deltas and repeated message snapshots from the standard trace.
- Verify the report and context do not depend on excluded raw events.

### End-to-end acceptance case

Use an ordered instruction set in which:

1. an early turn opens IEEE-39 and creates a converged AC result;
2. a later turn ranks branches using that exact result reference;
3. a final turn uses prior verified state in an N-1 analysis;
4. the report displays the result dependency chain and context revision flow;
5. the output directory contains the copied input, all per-turn answers, one report, one context ledger, one final snapshot, and shared evidence;
6. the standard trace remains bounded and contains no token-level streaming snapshots.

Run focused tests first, then the repository gates:

```sh
make doctor
make test
make test-e2e
make validate
```

Provider-billed validation is not part of the default verification and requires explicit credentials and authorization.

## Migration and Compatibility

- Existing single-question `grid-agent run` behavior and envelope remain supported.
- Existing historical run directories remain untouched.
- `make report` delegates to the new one-shot analysis runner during migration.
- The old independent `--output` and `--report-path` destinations are replaced by the analysis-directory invariant; documentation and Makefile examples point to the generated paths inside that directory.
- The human report retains the submitted-answer and non-blocking-audit behavior introduced by the current audit design.
- No user `var/` data is deleted or migrated.

## Acceptance Criteria

The design is complete when all of the following are true:

1. One instruction file is executed by one Pi process in strict order.
2. Later instructions receive a deterministic view of verified earlier state.
3. Actual tool inputs make cross-turn result reuse visible and testable.
4. One analysis directory contains the copied input, JSONL answers, report, trace, turns, context, results, and evidence.
5. The global simulator baseline is not repeated as though it were per-turn task state.
6. Every promoted numerical or network fact traces to verified gridctl output and the matching simulator revision.
7. The context ledger replays to the same final snapshot and state hash.
8. Answer audit diagnostics remain non-blocking and cannot rewrite submitted answers.
9. Genuine simulator-artifact integrity failure prevents untrusted state from flowing into a later instruction.
10. Standard traces exclude streaming deltas and remain practically inspectable.
11. stdout contains one valid answer envelope and diagnostics remain on stderr.
12. Architecture documentation, JSON Schemas, reducer behavior, report fields, and tests describe the same context contract.
