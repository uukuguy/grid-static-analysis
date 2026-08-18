# Readable Agent Analysis Trajectory Report Design

## Problem

The evidence-first report change made recorded tool output authoritative, but it
also made the report substantially harder to read. The main report currently
places `仿真与工具结果` before the answer and expands every tool result as JSON.
In a representative nine-question run, the report grew to 1,414 lines and the
first answer did not appear until line 180. Preparation calls such as
`model.list` dominated the page, while the previously useful
`仿真环境上下文` section disappeared.

The earlier compact trajectory had the opposite weakness: it usually reduced a
step to a generic capability label, status, and duration. Although the runtime
already records tool arguments and structured results, the report discarded
most of that information. This made repeated calls indistinguishable and gave
operators too little information to diagnose incorrect queries, recovery
actions, result reuse, or why a later analysis step followed an earlier result.

## Goals

- Put the reader-facing answer first for every question.
- Restore the simulation environment context as a first-class section.
- Make the observable agent analysis trajectory the explanatory backbone of
  the report.
- Embed compact, diagnostic simulator results in their corresponding trajectory
  steps instead of presenting a separate JSON-heavy result dump.
- Preserve failures, limitations, result reuse, and recorded decisions without
  inventing hidden model reasoning.
- Keep complete inputs, outputs, references, and artifacts available through
  each turn's detailed `trace.md`.
- Bound the main report so that trajectory detail improves diagnosis without
  overwhelming ordinary reading.

## Non-goals

- Exposing private chain-of-thought or reconstructing unrecorded model motives.
- Asking the LLM to call a mandatory narration or decision tool after every
  step.
- Semantically re-evaluating simulator facts in the reporting layer.
- Removing raw trace data or current-run evidence artifacts.
- Changing the controller-owned answer submission architecture.

## Per-question Report Structure

Each question uses this fixed order:

1. `### 回答`
2. `### 仿真环境上下文`
3. `### 智能体分析轨迹`
4. `### 执行状态与证据`

`## 完整性诊断` remains a batch-level section at the end of the report. It may
describe missing or malformed artifacts and broken references, but it must not
judge or rewrite simulator results or the model conclusion.

### Answer

The accepted reader-facing model text is the first content under the question.
A failed turn instead displays `模型未返回可接受的最终回答。` without hiding
successful simulator work already completed during that turn.

### Simulation Environment Context

Restore the existing deterministic context projection. It includes, when
available:

- active registered model and network size;
- applicable model-sourced constraints;
- calculations and convergence/completion status;
- scenarios created for the turn;
- calculations or results reused from prior questions.

This section is a semantic view of the active simulator context, not a raw
`context.open` result dump.

### Observable Agent Analysis Trajectory

The trajectory describes externally observable work only. Its sources of truth
are recorded capability contracts, tool arguments, structured simulator
results, current-run lineage, statuses, durations, limitations, and optional
`business.decision.declared` events. It never fabricates an explanation that
was not recorded or deterministically implied by the operation and its data.

Important simulator results are nested inside the step that produced them.
There is no separate `关键仿真结果` or `仿真与工具结果` section.

The normal milestone format is:

```text
2. 运行交流潮流（analysis.powerflow.ac.run，完成，1.28 秒）
   输入：默认运行方式。结果：收敛；有功网损 43.6275 MW。
   决策：超过模型约束 100%，后续进入线路 17 的 N-1 校核。
```

The decision line appears only when a real decision event, recorded limitation,
or deterministic recovery transition supports it.

### Execution Status and Evidence

Keep the turn status, total duration, original accepted-answer link, concise
evidence links, and detailed trajectory link. Complete tool inputs and outputs
belong in `turns/NNN/trace.md`, not in the main report.

## Trajectory Content Model

Every visible milestone should answer as many of these diagnostic questions as
the recorded data permits:

1. What task did this step perform?
2. Which capability performed it?
3. Which inputs materially changed its meaning?
4. What result or failure did it produce?
5. Did that result cause a recorded branch, recovery, or reuse action?

### Task Description

Generate a capability-specific work description from the operation contract and
key arguments. Descriptions must distinguish calls that use different models,
elements, datasets, filters, sort orders, limits, scenarios, or operations.
Unknown future capabilities use their capability ID and a compact description
of their selected key inputs rather than the repeated phrase
`调用已发布的领域能力`.

### Key Inputs

Render only parameters that affect the analytical meaning of the step, such as:

- model, element kind/index, branch or bus;
- operation and scenario;
- dataset and selected fields;
- filters, ordering, aggregation, comparison, and result limit;
- constraint quantity and threshold source.

Omit internal references, paths, nonces, hashes, credentials, transport fields,
and other implementation metadata. References used for lineage remain
available in the detailed trace and evidence artifacts.

### Key Results

Use capability-family projections to preserve diagnostic facts, including:

- environment/model identity and compact network counts;
- topology endpoints and connectivity;
- convergence, status, active-power loss, and unavailable quantities;
- dataset row counts and selected rows;
- ranking subjects, metric values, and units;
- constraint source, thresholds, violation counts, and violating subjects;
- contingency scenario count, convergence coverage, overloads, low voltages,
  and partial or failed outcomes;
- typed failure reason and remediation-relevant details.

Unknown capabilities receive a bounded scalar/summary projection. They must not
fall back to an unbounded JSON block in the main report.

### Decisions, Recovery, and Lineage

- Render `business.decision.declared` content only when it exists and can be
  associated with the current turn or step.
- Attach a decision to the step whose result supports it instead of creating a
  repetitive standalone node.
- Show a failed call and the later corrective call as a recovery sequence,
  including the changed semantic input.
- Show prior-result reuse as a compact relationship, for example
  `复用第 5 题交流潮流结果，未重复计算`.
- Do not require the LLM to call `grid_record_decision`. The controller and
  report remain correct when no explicit decision was declared.

## Information-density Contract

The main report is optimized for diagnosis and reading, not exhaustive event
replay.

- A normal milestone occupies two lines: a heading line and one combined
  key-input/key-result line.
- Add a third line only for a real decision, anomaly, limitation, or recovery.
- Merge adjacent setup calls such as `model.list`, `grid_guide_open`, and
  `context.open` into one `准备仿真环境` milestone.
- Merge identical retries, pagination calls, and repeated queries when their
  semantic inputs and outcomes are equivalent. State the count.
- Keep parameter or result differences visible when superficially similar calls
  are not equivalent.
- Attach decision records to their supporting milestone.
- Represent cross-question reuse in one line without repeating the original
  calculation.
- Target at most six visible milestones and approximately 20–25 trajectory
  lines per question. This is a compression target, not permission to remove
  distinct safety-relevant results.

The following must never be hidden merely to meet the target:

- tool failures and their concrete reasons;
- non-converged, partial, unavailable, or integrity-limited outcomes;
- the principal results supporting the answer;
- violations, rankings, contingency outcomes, and safety-relevant findings;
- recorded branch decisions and recovery actions.

When required information exceeds the target, retain the important milestones
and compress low-information setup or enumeration work. The detailed trace link
must always remain available.

## Deterministic Rendering Boundaries

The report renderer, not the model, owns trajectory compression and formatting.
It operates only on recorded data and capability-specific projection rules.
This keeps presentation provider-independent and prevents a missing narration
tool call from invalidating an otherwise correct analysis.

The renderer must continue to redact:

- internal `*_ref` and `*_refs` fields;
- secrets, passwords, credentials, API/private keys, authorization values, and
  token-shaped credential fields;
- internal paths, nonces, and content hashes from reader-facing prose.

Raw artifacts remain unchanged and linked for forensic inspection.

## Failure Behavior

- A failed turn still renders its answer placeholder first.
- Restored simulation context reflects the last valid context revision.
- Every successful result obtained before failure remains represented in the
  compact trajectory.
- The failing step includes its typed reason and any recorded recovery attempt.
- No successful answer or `analysis.completed` event is inferred from report
  formatting.

## Compatibility

- Historical `grid_submit_answer` events remain readable as legacy trajectory
  steps, but current reports do not instruct or expect the model to call it.
- Existing per-turn detailed trace pages remain the complete raw execution view.
- The CLI stdout envelope and stderr diagnostics contract does not change.
- Existing controller-owned answer and current-run evidence validation does not
  change.

## Verification Strategy

Add report tests that establish:

- `回答` precedes `仿真环境上下文`, which precedes `智能体分析轨迹`, which
  precedes `执行状态与证据`;
- the environment context contains active model, constraints, calculations,
  scenarios, and reuse information when present;
- the main report contains no expanded tool-result JSON fences;
- capability-specific milestones preserve distinctive endpoint, loss, ranking,
  dataset, violation, and contingency values;
- key arguments distinguish repeated calls;
- setup calls and identical retries are compacted;
- failures, partial results, recovery actions, and explicit decision events are
  retained;
- unknown capabilities use a bounded fallback;
- failed turns keep successful prior milestones;
- internal references and credential-shaped fields remain absent;
- the detailed trace and raw-artifact links remain present.

Run focused report tests first, then the analysis/E2E suites and the full offline
release gates. Provider-backed validation remains optional and must not be run
without explicit credentials and authorization.
