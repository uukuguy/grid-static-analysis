# Grid Static Analysis Agent Design

- Date: 2026-08-10
- Status: Approved design, pending written-spec review
- Governing requirement: `docs/TASK.md`

## 1. Purpose

Build a command-line-first agent that answers grid static-analysis questions by combining a proven long-horizon tool-calling runtime with an isolated pandapower 3.4.0 simulation environment.

The agent must be able to understand an open-ended question, discover and compose available grid capabilities, execute deterministic simulations when needed, and return an evidence-backed answer. The example questions in `docs/TASK.md` are acceptance samples only; they do not define a closed task taxonomy or a list of special-purpose workflows.

At every implementation stage, the primary command must remain usable:

```text
grid-agent run <question>
```

Every invocation returns the required envelope:

```json
{
  "question_id": "...",
  "answer_output": "..."
}
```

When a capability, input, or dependency is unavailable, the system returns a truthful limitation or failure explanation in the same envelope. It never fabricates simulation evidence.

## 2. Goals

1. Reuse the proven DCI/Pi long-horizon agent and tool loop without taking a runtime dependency on the downloaded DCI-Agent-Lite repository.
2. Isolate pandapower and its dependency stack behind a project-owned, engine-neutral protocol.
3. Model pandapower as a discoverable and composable interaction environment rather than a collection of handlers for example questions.
4. Combine simulation capabilities with concise first-party grid knowledge and session-local evidence.
5. Provide command-line operation, traceability, replay, deterministic evaluation, and configuration comparison without requiring external services.
6. Deliver a thin end-to-end question-answering path before expanding platform breadth.
7. Keep all numerical grid calculations and risk-policy computations deterministic and auditable.

## 3. Non-goals

The initial implementation will not:

- depend on files or import paths under `3th-party/`;
- expose arbitrary pandapower objects, DataFrames, or Python evaluation to the model;
- implement every pandapower feature before the first useful run;
- build a large knowledge base, embedding pipeline, or vector database;
- require MLflow, Langfuse, OpenTelemetry Collector, a web UI, or another daemon;
- use an LLM judge as the source of numerical correctness;
- specialize the code for the small set of examples in `docs/TASK.md`;
- automatically rewrite prompts or promote configurations without review.

## 4. Research Basis

The design uses the following projects as verified references, not application import dependencies:

- DCI-Agent-Lite commit `271f37e71f053bf0c99c05ce6d2fb53b841d922e`, MIT license.
- pandapower local `v3.4.0` tag commit `13638fc495778c25741dcfd40651d5c2d65094e7`, BSD-3-Clause license.

DCI's nearest benchmark analogue is BrowseComp-Plus because it stresses long-horizon decomposition, repeated tool calls, cross-checking, and evidence-grounded synthesis. BRIGHT is a secondary analogy for ranked results. No DCI benchmark is a direct analogue for a stateful simulator.

The reusable layer is the generic Pi runtime plus DCI-style RPC/event/artifact handling. In the downloaded runner, `PiRpcClient` already owns a reusable RPC subprocess and can frame repeated prompt cycles; the one-question behavior is imposed by the top-level runner. DCI's query-shaped recorder is an implementation reference for events and metrics, but the project needs session- and turn-shaped records.

## 5. Architectural Decisions

### 5.1 Harness

Use a project-owned adapter around a pinned Pi runtime.

- Pi owns model interaction, agent turns, tool calls, context management, and session continuity.
- `grid-agent` owns product sessions, turns, budgets, traces, answer envelopes, and evaluation.
- DCI benchmark runners and datasets are not imported.
- Adapted MIT-licensed logic retains attribution and notices.
- Pi is fetched and built from an independently pinned upstream repository and commit, recorded in `runtime/pi-runtime.lock.json` with checksums.

Replacing Pi with LangGraph or OpenAI Agents SDK is not part of the first release. The simulator and evidence protocols remain independent enough to permit a future runtime adapter if requirements change.

### 5.2 Simulator isolation

`grid-simulator` is a separate Python distribution and environment pinned to pandapower 3.4.0. `grid-agent` never imports pandapower.

The sidecar is a logical process boundary, not a requirement for an initially persistent service:

- Walking Skeleton: `gridctl` launches an isolated simulator process per call and exchanges JSON through stdin/stdout or files in the session workspace.
- Later optimization: a persistent sidecar may use the same protocol over process stdio or a session-scoped local socket.
- Persistence is adopted only if measured startup or repeated-load cost justifies its lifecycle complexity.

The protocol never exposes pandapower objects or internal DataFrame operations. It exposes stable network, revision, element, result, scenario, and artifact identifiers.

### 5.3 Capability-first environment

The interaction environment is defined from simulator capabilities and grid-domain knowledge. Example questions only test it.

The model sees three corpora:

1. A concise first-party knowledge corpus.
2. A machine-readable capability corpus.
3. A dynamic evidence corpus produced within the current session.

Common workflows are transparent recipes over public capabilities. They do not provide hidden functionality and are not task classifiers.

### 5.4 Local-first operations

All core operations work without a database or remote telemetry service.

- Append-only JSONL is the canonical trace format.
- Large artifacts are content-addressed files.
- SQLite is a later, rebuildable query index.
- HTML reports and external exporters are later derived views.
- Export failure never changes the result of an agent run.

## 6. Repository Structure

```text
grid-static-analysis/
├── packages/
│   ├── grid-agent/
│   │   └── src/grid_agent/
│   │       ├── cli/
│   │       ├── application/
│   │       ├── agent_runtime/
│   │       ├── simulator_client/
│   │       ├── evidence/
│   │       ├── observability/
│   │       ├── evaluation/
│   │       ├── experiments/
│   │       └── config/
│   ├── grid-simulator/
│   │   └── src/grid_simulator/
│   │       ├── protocol/
│   │       ├── capabilities/
│   │       ├── engines/pandapower_340/
│   │       ├── analyses/
│   │       └── evidence/
│   └── pi-grid-tools/
├── runtime/
│   ├── pi-runtime.lock.json
│   └── licenses/
├── configs/
│   ├── agents/
│   ├── prompts/
│   ├── policies/
│   ├── eval-suites/
│   └── experiments/
├── knowledge/
│   ├── index.json
│   ├── concepts/
│   ├── elements/
│   ├── analyses/
│   └── policies/
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   └── golden/
├── docs/
└── var/
```

`var/` is ignored by Git. Each package has an independent lock and build boundary. The main package does not acquire the simulator's scientific dependency stack.

No application source, test, build command, or runtime command refers to `3th-party/`. Those checkouts remain research-only material.

## 7. Runtime Components

### 7.1 GridSessionController

Responsibilities:

- accept CLI or evaluation-transport input;
- allocate or resume a product session;
- resolve configuration and record its fingerprint;
- launch or attach to Pi;
- prepare a session workspace and simulator access;
- enforce turn, tool, time, scenario, context, and artifact budgets;
- correlate Pi, tool, simulator, and evidence events;
- convert success or failure into the required answer envelope.

It does not perform grid calculations.

### 7.2 Pi runtime adapter

Responsibilities:

- launch the pinned Pi RPC runtime;
- send repeated prompts to a long-lived session;
- consume all RPC events until the current agent turn finishes;
- support abort, resume, context compaction, and runtime health checks;
- normalize Pi events into project trace events;
- preserve the Pi session file and its hash as a runtime artifact.

The adapter presents a project-owned interface so the application does not depend on DCI runner classes.

### 7.3 Simulator client and `gridctl`

`gridctl` is the initial executable bridge available to the agent through sandboxed Bash. It accepts schema-validated operations and returns compact JSON plus artifact references.

Responsibilities:

- validate the protocol version and engine handshake;
- map project identifiers to engine identifiers;
- invoke isolated simulator operations;
- externalize large results;
- return structured errors and evidence receipts;
- never print incidental logs to stdout.

The later `pi-grid-tools` package exposes the same operations as native Pi tools. It does not change simulator semantics.

### 7.4 Grid simulator

Responsibilities:

- load only allowlisted networks or explicitly supplied session inputs;
- create immutable base snapshots and explicit revisions;
- validate allowed state mutations;
- run deterministic analyses with explicit solver parameters;
- fail closed on non-convergence and exceptions;
- produce complete result and evidence artifacts;
- expose capability and version metadata.

Every operation starts from an identified network revision. Temporary contingency states are restored or discarded even on failure.

### 7.5 Knowledge and evidence access

The initial knowledge corpus is a small set of first-party Markdown/JSON cards searchable with `read` and `rg`.

Knowledge is separated into:

- invariant concepts: units, per-unit conventions, element semantics, and analysis concepts;
- configurable policies: operating ranges, limits, severity, and ranking policy;
- model facts: topology, parameters, operating state, and results from a specific revision.

Only model facts backed by current-session evidence may be presented as facts about the loaded network. A policy default is never presented as a universal electrical rule.

## 8. Command-line Contract

The command namespace is `grid-agent`.

### 8.1 Initial commands

```text
grid-agent doctor
grid-agent runtime install
grid-agent run
```

`grid-agent run` accepts a question argument, a JSON object, or an input file. Its default stdout is exactly one JSON answer envelope. Progress and diagnostics go to stderr. A human-oriented final rendering is available only through an explicit `--format text` option.

When the caller supplies `question_id`, the command preserves it. For plain-text interactive invocation without an ID, the CLI generates a unique ID and returns it in the envelope. Machine transports also generate an ID for malformed input that omitted one, then return an explicit protocol-error answer rather than emitting invalid output.

### 8.2 Expanded commands

```text
grid-agent chat
grid-agent serve --stdio

grid-agent sessions list
grid-agent sessions inspect ID
grid-agent sessions resume ID

grid-agent traces tail ID
grid-agent traces show ID
grid-agent traces export ID
grid-agent traces report ID --format html

grid-agent replay ID --mode recorded|tools|simulator
grid-agent eval run SUITE
grid-agent eval compare A B
grid-agent eval report RUN

grid-agent experiment run CONFIG
grid-agent experiment compare A B
```

`serve --stdio` is the default machine integration while the deployment environment is unknown. It consumes one JSON object per line containing `session_id`, `question_id`, and `question`, and emits one answer envelope per input line.

HTTP or another transport may be added as an adapter over the same application layer. Transport logic does not enter the agent or simulator core.

## 9. Capability Model

### 9.1 Descriptor

Each capability has a project-owned descriptor containing:

- stable ID and schema version;
- support status;
- concise semantic description;
- input and output schema;
- preconditions;
- state effect;
- cost and risk class;
- documented failure modes;
- evidence contract;
- engine binding and version constraints.

Support statuses are:

- `verified`: contract-tested with numerical or behavioral baselines;
- `available`: integrated with basic tests;
- `experimental`: exposed with documented limitations;
- `unsupported`: intentionally unavailable with a reason.

### 9.2 Discovery and knowledge

```text
capabilities.list
capabilities.search
capabilities.describe
knowledge.search
knowledge.read
```

The agent discovers capability constraints instead of relying on a system prompt that enumerates all pandapower behavior.

### 9.3 Network and state primitives

```text
network.list
network.open
network.describe
network.schema
network.query
element.resolve
topology.query
scenario.fork
scenario.patch
scenario.diff
scenario.reset
```

`scenario.patch` accepts only allowlisted, typed element fields. It creates a revision and supports dry-run validation. It never accepts Python or Pandas expressions.

### 9.4 Analyses

The registry can represent pandapower's broader capability set, including:

- balanced AC, DC, and three-phase power flow;
- diagnostics and topology searches;
- contingency analysis;
- optimal power flow;
- short-circuit calculation;
- state estimation and bad-data analysis;
- controller and time-series simulation;
- grid equivalents and protection;
- model creation, persistence, and conversion.

The first verified release profile, `static-analysis-v1`, prioritizes:

- network load, schema, query, and identifier resolution;
- controlled operating-state revisions;
- topology and supply-area analysis;
- AC/DC power flow and diagnostics;
- result query, aggregation, comparison, and evidence extraction;
- limits and sequential contingency analysis.

Other capabilities are described truthfully according to their implemented and tested maturity. Architecture breadth does not create a requirement to implement every capability before the walking skeleton.

### 9.5 Results and evidence

```text
results.schema
results.query
results.aggregate
results.compare
results.rank
limits.evaluate
evidence.explain
artifact.read
```

These are general result operations. For example, `results.rank` may rank any permitted numeric result field; it is not a special "top five lines" function.

Recipes such as critical-elements to contingencies to violations to risk ranking are inspectable compositions of public operations. They introduce no hidden simulator capability.

## 10. Network State and Evidence

### 10.1 State model

- A loaded base network is immutable.
- Each accepted modification creates a revision with a parent revision ID.
- An analysis references exactly one revision and explicit solver options.
- A contingency creates an ephemeral scenario from a revision.
- Failed or cancelled scenarios never mutate the parent revision.
- The session records which revision is current without deleting prior evidence.

### 10.2 Identifier model

Every element receipt includes:

- project-stable element ID;
- element type;
- source format and external/source identifier when available;
- engine table and engine index as internal provenance;
- human-readable name and connected project bus IDs.

Natural-language identifiers are resolved through `element.resolve`. Ambiguous identifiers return candidates and require clarification instead of silently choosing an engine index.

### 10.3 Evidence receipt

Every numerical claim can be linked to a receipt containing:

- session, turn, attempt, run, and scenario IDs;
- network and revision fingerprints;
- engine and engine version;
- capability and capability version;
- explicit solver and policy options;
- convergence and diagnostic status;
- element IDs and result field;
- value, unit, threshold, tolerance, and aggregation rule;
- artifact hashes and paths.

Full per-contingency results are retained. pandapower's aggregate extrema may be used as a cross-check but are not the only audit record.

## 11. Runtime Data and Observability

### 11.1 Hierarchy

```text
Experiment
└── Evaluation Run
    └── Session
        └── Turn
            └── Attempt
                └── Trace
                    └── Span
```

- A session is a continuous conversation.
- A turn corresponds to one `question_id`.
- An attempt is an original execution, retry, or replay.
- A trace is the causal execution for an attempt.
- Spans cover agent, model, tool, simulator, workflow, and evaluator work.

### 11.2 Event envelope

Each event includes:

- `schema_version` and monotonic `sequence`;
- timestamp;
- session, turn, attempt, trace, and optional span IDs;
- event type and status;
- structured attributes;
- artifact references.

Event families include `session.*`, `turn.*`, `agent.*`, `model.*`, `tool.*`, `simulator.*`, `evidence.*`, `guardrail.*`, and `evaluation.*`.

### 11.3 Local storage

```text
var/
├── index.sqlite
├── sessions/<session_id>/
│   ├── manifest.json
│   ├── events.jsonl
│   ├── pi-session/
│   ├── turns/<turn_id>/
│   │   ├── input.json
│   │   ├── output.json
│   │   └── metrics.json
│   ├── evidence/manifest.jsonl
│   └── artifacts/sha256/
└── experiments/<experiment_id>/
```

Only `manifest.json`, `events.jsonl`, turn input/output, evidence manifests, and required artifacts exist in the walking skeleton. SQLite and derived reports are added later.

JSONL append semantics make the last complete event recoverable after a crash. An interrupted attempt is marked as such during recovery.

### 11.4 Terminal observation

Default stderr output reports stages, tool and simulator progress, elapsed time, token use, and warnings. Supported output modes are:

- default human-readable progress;
- `--quiet` final output only;
- `--verbose` span and parameter summaries;
- `--json-events <path>` structured event copy.

Content capture is configured as `none`, `hash`, or `full`. The default captures structure and hashes, not complete model input and output content.

### 11.5 Exporters

OpenTelemetry, MLflow, and Langfuse are optional adapters over completed or streaming project events. The project event schema is authoritative because external GenAI schemas and platform versions may evolve.

Exporter errors are recorded locally and reported on stderr. They never fail an otherwise successful agent turn.

## 12. Answer and Degradation Contract

Every turn records one internal answer status:

- `answered_with_evidence`;
- `answered_from_general_knowledge`;
- `needs_clarification`;
- `unsupported_capability`;
- `execution_failed`.

The external output remains the two-field task envelope. `answer_output` explains the conclusion, evidence, clarification request, unsupported boundary, or execution failure as appropriate.

General grid knowledge may answer conceptual questions without a simulation. Claims about a loaded network require current-revision evidence. An unsupported or failed calculation cannot be replaced by an LLM estimate.

If Pi or the model fails before producing an answer, the `GridSessionController` returns an `execution_failed` envelope from a deterministic fallback formatter.

## 13. Evaluation

### 13.1 Hard gates

- valid task output schema;
- no incidental stdout output;
- pinned and recorded runtime/simulator versions;
- valid network and revision provenance;
- converged or explicitly failed analysis status;
- numerical conclusions linked to evidence;
- no model calculation of quantities assigned to deterministic tools;
- no example-specific code path.

### 13.2 Diagnostic metrics

- domain correctness: numeric tolerance, ranking, violation precision/recall, scenario coverage;
- trajectory: tool choice, redundant calls, errors, retries, and coverage;
- evidence: claim coverage, units, thresholds, provenance, and artifact integrity;
- robustness: ambiguity, invalid input, non-convergence, timeout, and recovery;
- efficiency: turns, calls, tokens, elapsed time, and optional model cost;
- language: completeness, clarity, and separation of conclusion from evidence.

Numerical, schema, and trajectory scorers are deterministic. An optional LLM judge may score language quality but cannot override a failed electrical-correctness gate.

### 13.3 Evaluation suites

Suites are versioned and capability-oriented. They include:

- individual capability contracts;
- capability compositions;
- held-out natural-language tasks not copied from `docs/TASK.md`;
- negative and failure cases;
- a small set of task examples as smoke tests.

The evaluator records the suite hash, reference data hash, configuration fingerprint, and scorer versions.

## 14. Replay and Experiments

### 14.1 Replay modes

- `recorded`: inspect the stored execution without invoking model or simulator;
- `tools`: run a model or prompt variant while replaying recorded tool results;
- `simulator`: replay recorded tool calls against the simulator to detect engine or protocol regressions.

A complete live rerun is an evaluation run, not deterministic replay.

### 14.2 Configuration fingerprint

Each attempt records:

- project Git commit and dirty state;
- Pi runtime commit and build hash;
- model, provider, and model parameters;
- system prompt and tool-schema hashes;
- context and compaction policy;
- turn, tool, token, time, scenario, and artifact budgets;
- simulator version and network fingerprint;
- solver, limits, evidence, and risk-policy versions;
- evaluation suite and scorer hashes.

### 14.3 Experiments

Experiments are declarative matrices over model, prompt, tool description, context policy, and budgets. They use paired cases and configurable repetitions.

Comparison reports hard-gate pass rate, correctness changes, token/time/cost changes, failure distributions, and per-case regressions. A candidate is not recommended unless hard gates pass and no critical regression is detected.

The first release stores experiment data locally. Automated prompt mutation and automatic configuration promotion are deferred.

## 15. Error Handling

### 15.1 Error categories

- ambiguous request or identifier;
- unsupported capability;
- capability precondition failure;
- invalid protocol or operation parameter;
- network/model validation failure;
- solver non-convergence;
- simulator exception or process failure;
- Pi/model failure;
- budget exhaustion or cancellation;
- trace/index/export failure.

### 15.2 Policy

- Ambiguity returns candidates or a clarification request.
- Validation failures identify fields and accepted constraints.
- Non-convergence preserves a failed receipt and may enable an explicit diagnostic capability; it does not silently change solver or physical assumptions.
- Transient process operations have a small, bounded retry policy. Non-idempotent operations are not automatically retried.
- Budget exhaustion stops further work and summarizes completed evidence and remaining gaps.
- Trace export and optional index errors do not affect the answer.
- All process cleanup uses `finally`-equivalent lifecycle handling.

## 16. Security and Resource Controls

### 16.1 Process access

- The simulator has no network requirement and receives only allowlisted paths and operations.
- Agent and simulator access is limited to the session workspace and approved read-only assets.
- Arbitrary Python evaluation is forbidden.
- Simulator state mutations are typed and revisioned.
- Initial Bash use is a feasibility mechanism and is clearly identified as a local-development profile.
- CI and formal deployment run Bash inside an external sandbox or replace it with native typed tools.

### 16.2 Budgets

Configurable hard limits cover:

- agent turns;
- tool calls;
- per-operation and total wall time;
- contingency scenario count and concurrency;
- model context and externalization threshold;
- artifact count and byte size;
- subprocess memory and CPU where the host provides enforcement.

The system records the effective budgets in every attempt fingerprint.

## 17. Verification Strategy

### 17.1 Unit and schema tests

- protocol and event schemas;
- identifier normalization;
- revision and state transitions;
- evidence receipt construction;
- answer fallback formatting;
- deterministic scorers and ranking policy.

### 17.2 Simulator contract tests

- independent pandapower 3.4.0 installation;
- network load and fingerprint;
- AC/DC power flow with explicit options;
- topology and supply checks;
- sequential contingency with complete scenario receipts;
- non-convergence and invalid-model behavior;
- state restoration after failure;
- stable project IDs independent of DataFrame index presentation.

### 17.3 Integration tests

- CLI to Pi to `gridctl` to simulator to evidence to answer;
- clean stdout and diagnostic stderr;
- process crash and timeout degradation;
- Pi/model failure fallback;
- session and turn correlation;
- trace recovery after interruption;
- no source, test, or build dependency on `3th-party/`.

### 17.4 End-to-end tests

The walking skeleton must demonstrate:

- a general grid-knowledge answer;
- network model query and identifier resolution;
- evidence-backed AC power-flow answer;
- evidence-backed sequential contingency answer;
- honest unsupported-capability response;
- valid answer envelope after simulator or model failure.

Additional held-out tasks test novel capability composition. Example questions from `docs/TASK.md` remain a small smoke subset.

## 18. Incremental Delivery

### 18.1 Walking Skeleton

Deliver first:

- independent package skeletons and locks;
- pinned Pi runtime acquisition and health check;
- `grid-agent doctor` and `grid-agent run`;
- project-owned Pi RPC adapter for a single question;
- `gridctl` per-call isolated simulator process;
- the minimal static capability set;
- a short knowledge handbook;
- answer fallback contract;
- JSONL trace and evidence artifacts;
- IEEE-39 numerical baselines and end-to-end smoke tests.

This phase is complete only when a real question traverses the full path and produces the required answer envelope.

### 18.2 Usable Static Agent

Add:

- continuous sessions and turns;
- controlled network revisions;
- richer identifier, topology, diagnostics, and contingency evidence;
- terminal trace inspection;
- deterministic evaluation suites;
- recovery and complete resource budgets.

### 18.3 Hardened Tool Environment

Add after evidence shows value:

- native Pi typed tools;
- persistent simulator process;
- expanded capability registry and recipes;
- SQLite query index and static reports;
- replay and local experiment comparison.

### 18.4 Optional Integrations and Capability Expansion

Add independently:

- OpenTelemetry, MLflow, or Langfuse exporters;
- HTTP/API transport;
- larger curated knowledge/search facilities;
- OPF, three-phase flow, short circuit, state estimation, time series/control, equivalents, protection, and converters according to tested demand.

Every phase preserves a working `grid-agent run` path. Platform breadth may not block or replace the core question-answering outcome.

The first implementation plan derived from this design is limited to Section 18.1, Walking Skeleton. Sections 18.2 through 18.4 require separate follow-on plans after the preceding phase is running and verified. This prevents the governing architecture from becoming a requirement to build the full platform before answering the first real question.

## 19. Acceptance Criteria for the Design

The implementation conforms to this design when:

1. First-party build, test, and runtime paths do not require `3th-party/`.
2. `grid-agent run` always returns the required envelope.
3. Supported numerical answers are evidence-backed and reproducible with pandapower 3.4.0.
4. Unsupported, ambiguous, and failed work degrades explicitly without fabricated results.
5. The agent discovers and composes capability-oriented operations rather than dispatching on example questions.
6. The knowledge corpus remains concise and distinguishes concepts, policies, and model facts.
7. Core tracing and evaluation work locally without services.
8. Runtime, simulator, configuration, policy, and evidence versions are auditable.
9. The walking skeleton is delivered before optional platform components.

## 20. References

- Main requirements: `docs/TASK.md`
- DCI paper: https://arxiv.org/abs/2605.05242
- DCI-Agent-Lite: https://github.com/DCI-Agent/DCI-Agent-Lite
- Pi SDK: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/sdk.md
- Pi RPC: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/rpc.md
- Pi sessions: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session.md
- Pi extensions: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md
- pandapower 3.4.0 documentation: https://pandapower.readthedocs.io/en/develop/
- pandapower contingency: https://pandapower.readthedocs.io/en/latest/contingency.html
- pandapower diagnostics: https://pandapower.readthedocs.io/en/latest/powerflow/diagnostic.html
- OpenTelemetry GenAI attributes: https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- MLflow GenAI tracing: https://mlflow.org/docs/latest/genai/tracing
- Langfuse self-hosting: https://langfuse.com/self-hosting
