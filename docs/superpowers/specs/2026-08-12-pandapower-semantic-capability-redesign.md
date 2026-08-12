# Pandapower Semantic Capability System Redesign

- Date: 2026-08-12
- Status: Approved
- Governing requirement: `docs/TASK.md`
- Implementation baseline: Git tag `v0.1` (`5cf2e2d`)
- Supersedes for future implementation:
  - `2026-08-10-grid-static-analysis-agent-design.md`
  - `2026-08-11-gse-agent-tooling-design.md`

## 1. Purpose

Rebuild the project as a natural-language power-system analysis agent that can make broad, reliable use of pandapower 3.4.0 through domain-semantic tools, a complete operational Skill, deterministic simulation, long-horizon orchestration, and evidence-backed answers.

The examples in `docs/TASK.md` are mandatory acceptance cases, not the system's capability boundary. The project will maintain a growing validation corpus covering individual pandapower capabilities, multi-step analysis, continuous dialogue, failure recovery, and held-out generalization.

The redesign retains the direct, comprehensible domain-tool experience demonstrated by `v0.1`, while removing its question-specific prompt workflows and narrow operation set. It selectively reuses the valuable isolation, revision, evidence, typed-error, checkpoint, context-management, and MCP lessons from the later GSE work without inheriting its premature abstractions.

## 2. Evidence Behind the Redesign

### 2.1 `v0.1`

`v0.1` is the tagged pre-GSE runnable baseline and a direct ancestor of the current main branch. Its model-facing `grid_query` operations used recognizable domain concepts such as network opening, element resolution, AC power flow, result ranking, and line contingencies. The accompanying prompt gave the model enough operational guidance to complete simple tasks with short tool paths.

Its limitations are equally important:

- a small, closed operation set;
- IEEE-39-specific behavior;
- fixed question-pattern workflows in the system prompt;
- protocol and tool descriptions too small to grow into broad pandapower coverage;
- incomplete real-provider validation beyond selected flows.

`v0.1` is therefore a behavioral reference and implementation starting point, not a design to restore unchanged.

### 2.2 Later GSE implementation

The later GSE work added useful infrastructure: typed protocol errors, immutable revisions, stable references, deterministic analyses, evidence and artifacts, long-horizon checkpoints, tool-result externalization, and an MCP adapter.

The observed live-provider failure exposed a central design defect. Capability descriptors primarily described protocol shape, risk, and persistence, but not enough domain purpose, object semantics, result meaning, composition, or recovery. Natural-language capability selection degraded to lexical matching, while generic data inspection required the model to guess allowlisted fields. The result was a loop through discovery, asset resolution, data inspection, and field errors for a question that should need one or two domain calls.

The redesign treats this as an architectural problem rather than a missing-field bug.

### 2.3 External references

The Datathings pandapower 3.4.0 Skill demonstrates useful domain coverage and progressive reference organization across network construction, topology, AC/DC power flow, OPF, short circuit, state estimation, time series, toolbox operations, plotting, and complete workflows.

PowerMCP demonstrates the usability of directly named power-system tools. Its global mutable network, raw DataFrame-shaped results, broad file access, and server-local calculations do not satisfy this project's isolation and evidence requirements, so it is a semantic and coverage reference rather than an execution dependency.

Official pandapower 3.4.0 documentation remains authoritative for supported functions, parameters, result meanings, limitations, and version behavior.

## 3. Goals

1. Make pandapower 3.4.0 capabilities understandable and usable through precise power-system semantics.
2. Support open-ended static-analysis questions and multi-step combinations rather than a closed list of example handlers.
3. Keep all numerical work inside a pinned, isolated simulator boundary.
4. Give the agent complete operational knowledge through a real, tested Skill rather than a placeholder prompt.
5. Use Pi/DCI capabilities for long tool sequences, structured progress, context control, interruption recovery, and continuous dialogue.
6. Preserve trustworthy result, evidence, error, and answer contracts.
7. Generate Pi and MCP tool surfaces from the same capability contracts.
8. Maintain a growing validation corpus that distinguishes simulator correctness, tool usability, agent planning, long-horizon reliability, and final-answer correctness.
9. Support the complete model lifecycle in the architecture while prioritizing analysis of registered, read-only networks in the first delivery.
10. Remove superseded implementations instead of retaining multiple protocols and tool paths indefinitely.

## 4. Non-goals and Priorities

The first delivery does not prioritize:

- creating networks from scratch;
- importing arbitrary user files;
- modifying registered networks;
- exposing every pandapower module at once;
- supporting multiple simulation engines;
- a web interface or remote service;
- arbitrary Python, shell, pandas, or `pandapowerNet` access;
- preserving compatibility with unconsumed experimental GSE interfaces.

The architecture defines creation, import, and modification as operations producing immutable revisions. Their implementation follows the registered-network read-only analysis path.

## 5. Architectural Principles

### 5.1 Pandapower is the designated simulator

Pandapower 3.4.0 is not an incidental first adapter. It is the required simulator and the primary capability source for this project. Public tools use power-system semantics, while capability contracts retain explicit pandapower provenance and version bindings.

Multi-engine neutrality is deferred. Boundaries should remain clean enough to avoid unnecessary coupling, but no abstraction is added solely for a hypothetical second engine.

### 5.2 Domain semantics precede protocol abstraction

The public unit is a domain capability such as resolving a line, retrieving branch endpoints, running AC power flow, evaluating N-1 scenarios, or ranking violations. A generic protocol invocation remains an internal transport mechanism and is not the model's primary mental model.

### 5.3 Tools and Skill are complementary

- Tool descriptions specify what an operation does and exactly how to call it.
- The Skill explains when to use operations, how to select parameters, how to combine results, how to diagnose failures, and how to interpret evidence.
- Pi/DCI executes and maintains long-running work.
- GSE validates and executes deterministic operations.

No layer may compensate for unusable tool descriptions by forcing the model to guess.

### 5.4 Simple questions remain simple

A topology fact must not require power flow, capability search, or generic field probing. Explicit plans and checkpoints are used when tasks actually require several analysis stages, batch scenarios, or recovery.

### 5.5 Full results exist outside model context

Complete simulator results are persisted before the model receives a bounded view. Context compaction changes only the model view; it never deletes result or evidence data.

### 5.6 One semantic source, several transports

Capability contracts are the single executable semantic source. Pi tools, MCP tools, schemas, generated references, validation fixtures, and simulator dispatch all derive from or validate against them. MCP and JSONL do not define alternative domain models.

## 6. System Architecture

```text
User / evaluation transport
            |
            v
grid-agent
  - session and turn controller
  - Pi/DCI runtime adapter
  - plan/checkpoint controller
  - answer and evidence verifier
            |
            +---- controlled Skill guide access
            |
            v
Domain capability packages
  - semantic contracts
  - typed tools
  - composition metadata
  - validation assets
            |
            v
GSE execution kernel
  - registered models and immutable revisions
  - schema/state/budget validation
  - results, errors, evidence, artifacts
            |
            v
Pandapower 3.4.0 binding

The same capability contracts also project to:
  - Pi native tools
  - MCP tools/resources
  - JSONL requests/responses
```

### 6.1 `grid-agent`

`grid-agent` owns:

- the CLI and final `{question_id, answer_output}` envelope;
- product sessions and continuous dialogue;
- loading the current registered model and revision context;
- attaching the Skill and capability tools to Pi;
- structured plans, attempt state, budgets, checkpoints, and resume;
- answer composition and evidence verification;
- human-readable progress on stderr and final JSON only on stdout.

It never performs electrical calculations or reads pandapower objects.

Reviewed conceptual questions, such as the meaning of operating limits or the required inputs to a calculation, may be answered from the Skill without opening a simulator run. Such offline informational answers do not create a run workspace or claim simulator evidence.

### 6.2 Domain capability packages

A capability package is the principal extension unit. It owns related contracts, tools, semantic guidance links, pandapower bindings, and validation coverage.

Initial packages are:

- `model-context`;
- `model-data`;
- `topology`;
- `power-flow`;
- `contingency`;
- `result-analysis`;
- `policy-risk`;
- `evidence`.

Planned packages include OPF, short circuit, state estimation, time series, and model lifecycle operations.

### 6.3 GSE execution kernel

GSE is retained as a small execution kernel rather than an isolated conceptual platform. It owns:

- model registration and lookup;
- immutable revisions and analysis contexts;
- capability invocation validation;
- result, evidence, artifact, and error persistence;
- budget and state enforcement;
- pandapower process isolation.

It does not perform unrestricted natural-language intent matching, decide which analysis the user intended, or expose a generic guessable data facet.

### 6.4 Pandapower binding

The binding maps domain inputs to pandapower 3.4.0 calls and normalizes outputs. It may use pandapower DataFrames internally, but model-facing results are typed domain records with units, identifiers, result provenance, and stable references.

## 7. Capability Contract

Every executable capability declares at least:

```json
{
  "id": "topology.branch.endpoints.get",
  "version": "1.0.0",
  "package": "topology",
  "title": "Get branch endpoint buses",
  "purpose": "Return the two buses connected by a line or transformer",
  "applies_to": ["line", "transformer", "transformer3w"],
  "not_for": ["power-flow direction"],
  "terms": ["连接母线", "首末端", "两端", "endpoint buses"],
  "inputs": {},
  "outputs": {},
  "requires": ["analysis_context", "branch_ref"],
  "consumes": ["network.branch"],
  "produces": ["topology.endpoints", "evidence.network_fact"],
  "common_next": ["topology.neighbors", "powerflow.ac.run"],
  "errors": [],
  "recovery": [],
  "state_effect": "none",
  "evidence": {},
  "pandapower": {
    "version": "3.4.0",
    "binding": "line.from_bus/to_bus or transformer bus fields"
  }
}
```

The contract must describe:

- user purpose and professional terminology, including Chinese and English aliases;
- applicable and inapplicable object types;
- complete typed input and output schemas;
- semantic types consumed and produced;
- preconditions and state effects;
- common composition edges without prescribing a fixed workflow;
- parameter meanings, units, defaults, and default authority;
- supported errors and legal recovery actions;
- cost, risk, and budget dimensions;
- evidence obligations;
- exact pandapower 3.4.0 binding and limitations;
- linked validation cases.

Capability discovery searches structured semantic metadata. It may use lexical, semantic, or model-assisted ranking as a guide, but it may not hide tools or decide user intent solely through substring matching.

## 8. Complete Operational Skill

### 8.1 Role

The Skill is an operational power-system analysis manual for the agent. It replaces the fixed question workflows formerly embedded in `configs/prompts/grid-agent-system.md`, but does not replace precise tool descriptions.

The first published Skill must be complete for all implemented initial capability packages. Placeholder sections are not accepted.

### 8.2 Structure

```text
skills/grid-static-analysis/
├── SKILL.md
└── references/
    ├── capability-map.md
    ├── model-and-context.md
    ├── network-elements.md
    ├── topology-analysis.md
    ├── ac-dc-powerflow.md
    ├── contingency-analysis.md
    ├── result-query-and-comparison.md
    ├── policy-risk-and-evidence.md
    ├── convergence-and-recovery.md
    └── future/
        ├── opf.md
        ├── short-circuit.md
        ├── state-estimation.md
        └── time-series.md
```

`SKILL.md` is a concise navigation and operating contract. References use progressive disclosure. Implemented sections are complete and runnable; future sections clearly state that runtime support is unavailable.

### 8.3 Required content

Each implemented domain section includes:

- when the analysis is and is not applicable;
- concepts, terminology, units, and sign conventions;
- available capabilities and their input/output meanings;
- parameter selection and defaults;
- required contexts and result dependencies;
- single-step and multi-step examples;
- result inspection, filtering, aggregation, and comparison;
- convergence, ambiguity, missing-data, infeasibility, and partial-failure recovery;
- evidence requirements;
- prohibited shortcuts and common mistakes.

The Skill is checked against official pandapower 3.4.0 documentation. External Skills and MCP implementations are references, not copied authority.

### 8.4 Controlled runtime access

Pi does not receive a general filesystem `read` tool. Skill content is packaged and exposed through controlled read-only guide operations such as `grid_guide_open`. Only published Skill resources can be accessed through this interface.

### 8.5 Skill evaluation

Validation compares selected real-provider runs with and without Skill guidance. The evaluation measures capability selection, valid parameterization, tool-call efficiency, recovery, result interpretation, and evidence use. Final-text similarity alone is insufficient.

## 9. Tool Surface and Discovery

### 9.1 Stable foundation tools

A small stable tool set provides guide, model, context, capability-package, evidence, and answer operations:

```text
grid_guide_open
grid_models_list
grid_context_open
grid_context_get
grid_capability_packs
grid_capability_activate
grid_evidence_get
grid_submit_answer
```

### 9.2 Domain tools

Initial read-only analysis tools include direct operations for:

- listing and retrieving model elements;
- describing and querying typed datasets;
- topology neighbors, paths, components, endpoints, and unsupplied buses;
- AC and DC power flow;
- power-flow summaries and result views;
- N-1 execution and summaries;
- result filter, rank, compare, and aggregate;
- violation evaluation and risk ranking.

Names must express domain purpose. Tools must document inappropriate uses as well as intended uses.

### 9.3 Package activation

The agent chooses capability packages using the Skill and structured package summaries. The server validates availability and context applicability but does not infer user intent from question keywords.

If Pi cannot add tools during a live loop, activation creates a structured checkpoint and continues in a new tool-equipped segment. When the initial static-analysis tool count is manageable, all initial packages may be preloaded to reduce orchestration complexity. This is an evaluated runtime choice, not a fixed architectural requirement.

### 9.4 No arbitrary field guessing

The old `data.inspect(fields: string[])` pattern is removed. The execution kernel exposes typed domain datasets such as:

```text
network.buses
network.branches
network.generators
network.loads
network.transformers
powerflow.buses
powerflow.branches
powerflow.generators
contingency.scenarios
violations
```

Dataset description returns all queryable fields, types, units, meanings, origins, and supported predicates. Dataset query accepts only fields declared by that schema.

### 9.5 Identifiers

Stable opaque asset references are used for composition and evidence. Source identifiers remain explicit aliases, for example `pandapower:line:11`, so user references such as "线路11" remain resolvable. Source indices are not hidden when they are legitimate user-facing identifiers.

## 10. Runtime and DCI Collaboration

### 10.1 Execution flow

For a complex turn the agent:

1. identifies the goal, model, objects, method, operating assumptions, and requested output;
2. opens the relevant Skill guidance;
3. creates or updates a structured plan containing steps, expected result types, and evidence obligations;
4. invokes domain tools;
5. persists complete tool results and exposes bounded views plus stable references;
6. updates the plan using typed outcomes and recovery guidance;
7. checkpoints before expensive batches, compaction, interruption, or tool-surface changes;
8. queries, ranks, aggregates, or compares stored result references;
9. submits an answer whose verifiable claims are checked against evidence.

Simple turns may omit an explicit multi-step plan.

### 10.2 Durable state

State required for recovery is structured rather than transcript-only:

- current model, revision, and context;
- selected capability packages and their versions;
- plan steps and status;
- resolved asset references;
- result, evidence, and artifact references;
- active batch or recipe progress;
- budgets and attempt counters;
- tool-set and runtime-profile fingerprints.

### 10.3 Context management

- Persist full tool results before truncation or summarization.
- Preserve call/result pairing and stable result references.
- Keep recent bounded views inline and externalize older large results.
- Never rely on an LLM summary as the only copy of a numerical fact.
- Validate revision, capability, tool-set, and runtime identity on resume.

### 10.4 Recipes

Normal multi-step analysis is agent-composed using the Skill and capability relations. A deterministic recipe is introduced only for a stable, bounded, frequently repeated computation where server-side execution improves correctness or efficiency, such as batch N-1 evaluation. Recipes expose their constituent operations, partial-failure policy, checkpoints, and evidence.

## 11. Models, Revisions, and Lifecycle

### 11.1 Initial priority

The first implementation analyzes registered, read-only networks. It supports several fixed pandapower 3.4.0 networks to prevent IEEE-39 specialization.

### 11.2 Lifecycle design

The domain model supports:

```text
registered model
  -> immutable base revision
  -> derived revision from controlled import/create/modify operation
  -> analysis context
  -> analysis result
```

Read-only analysis never changes a revision. Future creation, import, and modification operations validate their input and produce new immutable revisions. They never give the model direct mutation access to a `pandapowerNet` or DataFrame.

## 12. Results and Evidence

Every simulator-backed result records:

- capability and version;
- validated arguments;
- model, revision, and context;
- pandapower version and effective solver options;
- convergence or partial-failure status;
- units and field provenance;
- result, artifact, and evidence references;
- attempt identity and timing.

Network-specific facts and numerical claims require current-run evidence. Conceptual answers may cite reviewed Skill knowledge and need not create simulator evidence. A failed evidence write prevents the result from being used as a supported claim.

`runs/<question_id>/` is created only when a question performs a simulator-backed network query or calculation. A purely informational answer leaves no run evidence directory.

The answer verifier checks that references exist in the current run, match the expected revision, and support the stated fields and values.

## 13. Error and Recovery Contract

Errors are typed and actionable. A failure includes:

- code and domain phase;
- message suitable for an agent;
- retryability;
- state effect;
- diagnostics, evidence, and artifact references;
- allowed recovery actions;
- valid values or schema information when parameter validation fails.

Rules:

- Only transient transport failures are automatically retried.
- Non-convergence, unobservability, OPF infeasibility, and scenario failure are domain outcomes.
- Partial batch success preserves both successful and failed scenarios.
- Context or revision mismatches fail closed.
- Missing or ambiguous assets request clarification or explicit resolution.
- Unsupported capabilities are reported truthfully.
- Repeated execution with changed solver assumptions is explicit and evidence records both attempts.

## 14. Security and Isolation

- Pandapower, pandas, NumPy, and SciPy remain outside the agent package.
- Pi receives no arbitrary shell, Python, filesystem, or raw simulator access.
- Registered model access is allowlisted.
- Tool inputs and outputs are schema validated.
- Large artifacts and Skill resources are accessed through scoped references.
- Secrets enter only the selected model-provider process and are never sent to the simulator.
- MCP invokes the same execution boundary and does not reimplement calculations.
- First-delivery permissions are read-only analysis.

## 15. Directory Layout

```text
configs/
├── agent/
│   └── system-policy.md
└── runtime/
    ├── pi-runtime.lock.json
    └── long-horizon-profile.json

skills/
└── grid-static-analysis/
    ├── SKILL.md
    └── references/

validation/
├── manifest.json
├── suites/
├── fixtures/
└── evaluators/

third-party-notices/
└── PI.md

.grid-agent/                 # ignored internal local state
├── auth/
├── runtime/pi/
└── sessions/

runs/                        # ignored operator-visible run records
└── <question_id>/
    ├── events.jsonl
    ├── plan.json
    ├── tool-results/
    ├── evidence/
    └── answer.json
```

The current `runtime/` versioned files move under descriptive versioned directories. The current `var/` content is split between `.grid-agent/` internal state and `runs/` auditable output.

Existing local `var/` data is not destructively removed during implementation. Authentication and historical evidence are migrated or explicitly archived first; cleanup is a separate documented operator action.

## 16. Validation Corpus

### 16.1 Case format

Each validation case specifies:

- question and optional dialogue history;
- suites and tags;
- registered model and initial context;
- required and forbidden capabilities where appropriate;
- tool-call or scenario budgets;
- evidence obligations;
- deterministic oracle and tolerance;
- expected failure or recovery behavior.

Tool trajectories are constrained by semantics, not by requiring one exact sequence when several valid plans exist.

### 16.2 Suites

- `task-required`: every example in `docs/TASK.md`;
- `static-analysis-core`: registered data, topology, AC/DC power flow, results, N-1, policy, and risk;
- `composition`: multi-package and multi-stage tasks;
- `dialogue`: references, inherited conditions, model changes, and corrections;
- `recovery`: ambiguity, missing input, missing objects, non-convergence, partial failure, interruption, and resume;
- `held-out`: expression variants, networks, and combinations not used to author the Skill.

### 16.3 Capability contribution rule

Every newly supported capability adds:

- at least one single-capability case;
- at least one composition case;
- at least one failure or boundary case;
- a deterministic evaluator;
- held-out coverage when applicable.

### 16.4 Evaluation dimensions

The harness separately measures:

1. domain understanding;
2. tool choice and argument validity;
3. numerical and structural correctness;
4. evidence completeness;
5. final answer completeness and honesty;
6. tool-call efficiency;
7. recovery and resume success;
8. token, time, and provider cost.

Numerical grading uses pandapower 3.4.0 fixtures and deterministic evaluators. LLM judges are optional secondary signals and never determine numerical correctness.

### 16.5 Test levels

- Fast CI: contracts, schemas, adapter goldens, evaluators, and security boundaries.
- System CI: deterministic scripted-agent flows without a paid provider.
- Provider regression: representative cases on real configured models.
- Release gate: all mandatory TASK cases, all deterministic core cases, zero fabricated evidence, no regression in supported capabilities, and versioned held-out thresholds.

Reports use a coverage matrix across capability package, model, question type, language expression, composition depth, and success/failure behavior.

## 17. Migration Strategy

### 17.1 Branching

Implementation starts on a new branch and isolated worktree based on tag `v0.1`. The current main branch remains the history of the GSE experiment. The approved design specification is brought into the new branch explicitly.

The existing uncommitted `Makefile` and unrelated worktrees are not modified or discarded.

### 17.2 WP-A: semantic foundation and validation baseline

- Create the validation corpus and deterministic evaluators.
- Define the capability contract and initial packages.
- Implement registered-model, element, topology, and typed dataset access.
- Cut over from legacy `grid_query` descriptions to direct domain tools.
- Remove fixed question workflows and protocol 1.0 at cutover.
- Pass TASK informational and topology cases through the real tool path.

### 17.3 WP-B: complete static-analysis capability

- Implement AC/DC power flow, result access, rank, filter, aggregate, and compare.
- Implement N-1, violations, risk, and partial-failure handling.
- Publish the complete initial Skill and references.
- Support multiple registered pandapower networks.
- Pass TASK, static-analysis-core, and composition suites.

### 17.4 WP-C: DCI long-horizon collaboration

Selectively port and simplify:

- complete tool-result externalization;
- structured plans and checkpoints;
- context/revision/result/evidence recovery;
- tool, scenario, time, artifact, and context budgets;
- continuous dialogue and process-restart resume;
- provider-context recording and compaction.

The old lexical projection logic, descriptor-bound assumptions, and deterministic-fake performance claims are not ported. Long-horizon features must demonstrate value on real composition, recovery, and held-out cases.

### 17.5 WP-D: unified transports and release

- Generate Pi and MCP tools from the same contracts.
- Rebuild a small `grid-mcp` transport adapter.
- Prove JSONL, Pi, and MCP semantic conformance.
- Complete directory migration and operator documentation.
- Remove temporary compatibility paths and superseded generated files.
- Pass the full release gate.

Every work package leaves `grid-agent run` functional and preserves the stdout contract.

## 18. Deletion and Cleanup

The new implementation removes rather than retains:

- `configs/prompts/grid-agent-system.md`;
- legacy `grid_query` and `hardened-bash.mjs`;
- protocol 1.0 and GSE compatibility aliases;
- lexical `IntentResolver` and `CapabilityResolver`;
- arbitrary `data.inspect` field guessing;
- old descriptor-derived generated capability documentation;
- the current descriptor-bound `gse-tools.mjs`;
- the current `grid-mcp` implementation before rebuilding it from new contracts;
- obsolete architecture plans, generated artifacts, and status claims that describe removed behavior.

The repository will expose one protocol version, one capability-contract system, one Pi projection, and one MCP projection. Compatibility code requires a named external consumer and a removal version; otherwise it is not added.

Git history and the `v0.1` tag preserve prior implementations.

## 19. Selective Reuse

Review and port where valuable:

- isolated simulator packaging;
- typed error structure;
- immutable revision and stable-reference mechanics;
- evidence and artifact persistence;
- safe long-horizon externalization, checkpoints, and resume validation;
- MCP transport and conformance-test techniques.

Reimplement:

- capability contracts and tool descriptions;
- the complete Skill;
- model, element, topology, and result views;
- agent planning entry point;
- recipe criteria and execution;
- Pi tool materialization;
- MCP catalog;
- validation corpus and evaluators.

Do not port abstractions whose benefit is not demonstrated by target questions or capability growth.

## 20. Completion Criteria

The redesign is complete only when:

- all `docs/TASK.md` cases pass;
- the versioned static-analysis coverage matrix meets its release threshold;
- multiple registered networks and continuous dialogue are validated;
- held-out questions demonstrate generalization beyond authored examples;
- all numerical answers are deterministically checked against pandapower 3.4.0;
- no arbitrary field guessing, fabricated evidence, or boundary bypass occurs;
- simple questions take short, direct tool paths;
- complex questions can plan, checkpoint, recover, and complete;
- Skill-enabled provider runs demonstrate improved tool selection and recovery;
- only one active protocol and tool system remains;
- the code tree and operator documentation reflect the actual architecture.

## 21. Design Invariants

1. `stdout` contains only the final JSON answer envelope.
2. Numerical power-system work is performed by isolated pandapower 3.4.0 execution.
3. The model never receives arbitrary Python, shell, DataFrame, or `pandapowerNet` access.
4. Tool descriptions remain independently usable; the Skill does not conceal deficient schemas.
5. The Skill is complete for every advertised initial capability.
6. GSE executes domain contracts and does not guess unrestricted language intent.
7. Full results and evidence survive model-context compaction.
8. Network-specific and numerical claims require matching current-run evidence.
9. MCP and Pi are projections of the same contracts.
10. `docs/TASK.md` is a mandatory baseline, not a closed taxonomy.
11. Validation grows with every capability.
12. Legacy paths are removed at cutover instead of becoming permanent alternatives.
