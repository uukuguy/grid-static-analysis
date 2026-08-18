# Controller-Owned Answer Submission and Evidence-First Report Design

**Date:** 2026-08-18  
**Status:** approved design; implementation pending  
**Supersedes:** model-owned `grid_submit_answer` as the required terminal action and report rendering that treats an accepted answer draft as the sole reader-facing result

## 1. Problem

The current online execution path asks the model to call `grid_submit_answer`
after it finishes reasoning. The RPC layer already returns the model's ordinary
final text, but callers discard that value and instead wait for the tool to
write an answer draft. Tool calling is provider- and model-dependent, so a model
can successfully run grid tools, return a usable final answer, and still fail
the turn merely because it did not make the extra submission call.

Continuous analysis compounds this defect. A missing draft produces a failed
turn, but the runner can continue and later emit `analysis.completed` once all
turn records exist. The resulting manifest can say `completed` while every turn
is failed.

The report then treats the accepted answer draft as the primary answer. Tool
results are reduced to a small set of hard-coded summaries or generic operation
labels. Consequently, valid simulator facts visible in the execution trace can
be absent from the main report, especially when answer submission failed.

These are orchestration and projection defects. They must not be delegated to
an evaluator or repaired by asking the model to follow the submission prompt
more reliably.

## 2. Design objectives

1. Make answer submission a deterministic controller responsibility.
2. Keep the model responsible for analysis-tool selection and reader-facing
   answer composition, not persistence or internal reference bookkeeping.
3. Make successful `gridctl` results the factual authority in the report.
4. Preserve useful tool results in partial reports even when a turn or batch
   fails.
5. Permit `analysis.completed` only when every required turn succeeds.
6. Preserve the CLI contract: exactly one JSON object on stdout and diagnostics
   on stderr.
7. Keep numerical and network-specific claims behind `gridctl` and
   `grid-capability` protocol version `1.0`.

## 3. Responsibility boundary

### 3.1 Model

The model may:

- interpret the question;
- inspect the bounded analysis context;
- call registered grid analysis tools and `grid_guide_open`;
- return a non-empty, reader-facing final text response.

The model does not decide whether the answer should be committed, write answer
artifacts, bind an answer to a turn nonce, or enumerate internal content
references.

### 3.2 Simulator

`gridctl` remains the only authority for network-specific and numerical facts.
It persists deterministic results and evidence through the existing capability
protocol. No report or controller code recreates pandapower calculations.

### 3.3 Controller

The controller:

- receives the final text returned by `PiRpcClient.prompt_and_wait`;
- rejects an empty final response;
- derives the turn's answer-level result and evidence references from the
  context already projected from successful tool calls;
- writes and validates the answer draft and answer envelope;
- records `answer.submitted` before the terminal turn event;
- determines turn and batch status.

`grid_submit_answer` becomes an internal submission operation rather than a
model-visible tool.

### 3.4 Report renderer

The renderer deterministically projects recorded tool events, simulator
results, submitted answer text, status, and integrity diagnostics. It does not
invoke an LLM, score semantic correctness, or override simulator facts.

## 4. Execution flow

For each online question or continuous-analysis turn:

```text
controller starts turn
  -> model calls zero or more permitted grid tools
  -> successful tool results are verified and projected
  -> model returns ordinary final text
  -> controller rejects empty text or commits non-empty text
  -> controller records the terminal turn event
```

The analysis prompt tells the model to provide a final reader-facing response,
but does not mention or require a submission tool. There is no corrective
prompt whose purpose is to induce a missing `grid_submit_answer` call.

The single-question `run` command and continuous `analysis` command use the
same ownership rule. The Pi extension no longer registers
`grid_submit_answer`, so behavior cannot vary according to whether a provider
chooses to call it.

## 5. Controller-owned submission

### 5.1 Final text

`prompt_and_wait` must return non-empty public answer text. Reasoning-only,
tool-only, provider-error, and empty responses are not successful answers. The
controller does not synthesize missing prose from a trace and does not treat a
tool result alone as a completed model answer.

Tool facts from such a failed attempt remain available to the partial report.

### 5.2 Reference collection

For continuous analysis, the controller derives answer-level references from
the active turn's `consumed_refs` and `produced_refs` after all semantic events
have been projected:

- references with the `result:sha256:` prefix populate `result_refs`;
- references with the `evidence:sha256:` prefix populate
  `claim_evidence_refs`;
- duplicates are removed while preserving observation order;
- context, observation, limitation, and unknown reference kinds are not placed
  in answer-level result/evidence fields.

Both consumed and produced references are considered because a later turn may
legitimately answer from results established earlier in the same continuous
session.

The controller does not fabricate per-claim categories or claim-to-reference
mappings. Structured `claims` are empty unless a future deterministic mechanism
defines them. Exact lineage remains available through tool observations,
results, evidence records, and the turn's answer-level references.

### 5.3 Artifacts and compatibility

The controller continues to create auditable answer artifacts with the active
turn ID, nonce, submission ID, final text, normalized references, and an empty
claims list. Existing answer validation, hashing, archival, `answer.submitted`,
`answer.json`, and `answers.jsonl` behavior remains in force after the draft is
created internally.

The model-facing implementation of `grid_submit_answer` and its tool events are
removed. Historical runs containing those events remain readable.

For the online single-question path, the final text returned by Pi becomes the
`answer_output` in the stdout envelope. Successful simulator references remain
recorded in the run workspace; no model-written answer draft is required.

## 6. Terminal state semantics

A turn succeeds only when:

1. the model request settles without a provider or protocol error;
2. the returned final text is non-empty;
3. controller-owned answer submission completes; and
4. the answer and trajectory artifacts pass their existing integrity checks.

Otherwise the turn is recorded as failed. The runner checkpoints a partial
report, marks the analysis failed, and stops before starting another required
turn.

An analysis may emit `analysis.completed` only when:

- there is no active turn;
- the number of terminal turn records equals the number of instructions;
- every turn has status `success` and an accepted answer path; and
- context and native-trajectory replay checks pass.

Any failed required turn yields `analysis.failed`, a failed manifest, CLI exit
code `1`, and a preserved report path. `completed_turns` continues to count
terminally processed turns for schema compatibility; success and failure counts
in the report disambiguate their outcomes.

## 7. Evidence-first report

Each turn is rendered in this order:

1. **Simulator and tool results** -- the factual body, in actual call order.
2. **Model conclusion** -- the submitted reader-facing text, when available.
3. **Execution status and evidence** -- duration, result/evidence lineage, and
   links to complete artifacts and the raw trace.
4. **Integrity diagnostics** -- missing, malformed, unavailable, or failed
   records without a second semantic judgment.

Every completed grid-tool call must have a visible representation in the main
report. Compact capability-specific renderers may improve readability, but a
generic structured fallback must preserve result fields for every published or
future capability. Large datasets may be summarized by deterministic metadata
and bounded rows when the main report links directly to the complete stored
result; they must not be reduced to only "called tool X".

Known high-value fields such as topology endpoints, convergence, losses,
ranking rows, dataset query rows, contingency status and scenarios must appear
in the main turn body when present in the recorded tool result. Their displayed
values must be taken directly from that result.

If the model conclusion is missing, the report says so and marks the turn
failed, but still renders every available tool result. The absence of an answer
artifact must never erase simulator facts.

The current "audit review" is narrowed to integrity diagnostics. It may report
broken links, invalid references, unavailable artifacts, or projection errors;
it may not decide that a simulator result is semantically wrong or replace the
model's conclusion.

## 8. Error handling

- Provider or RPC failure: fail the active turn and batch, then render captured
  results and diagnostics.
- Empty final text: fail with an explicit `model returned no final answer`
  diagnostic; do not reprompt for a submission tool.
- Internal submission validation failure: fail the turn and batch; retain the
  raw final text and tool trace for diagnosis without publishing it as an
  accepted answer.
- Tool failure handled by the model: it remains visible in the report and does
  not by itself force turn failure if the model produces an accurate limitation
  response.
- Context or trajectory integrity failure: retain existing fail-closed terminal
  behavior.

## 9. Verification strategy

Implementation follows test-driven development. Focused tests must first prove
the current defects and then protect the new behavior:

1. The Pi extension's model-visible tool list excludes
   `grid_submit_answer`.
2. The online single-question path publishes the non-empty RPC final text.
3. A continuous turn commits non-empty RPC final text without a model submission
   tool event.
4. Controller-generated drafts bind to the current turn and contain only
   current-run result/evidence references.
5. Empty final text fails the turn and batch.
6. A failed turn cannot be followed by `analysis.completed`.
7. Any failed required turn produces a failed manifest and CLI exit code `1`.
8. A failed turn's successful tool values remain in the main report.
9. Representative endpoint, power-flow, ranking, dataset-query, and contingency
   values in the report equal their recorded tool-result values.
10. Unknown capabilities use the structured fallback rather than a generic
    label.
11. Historical trajectories with `grid_submit_answer` remain readable.
12. All CLI paths retain the one-object stdout envelope contract.

After focused tests pass, verification uses `make test`, `make test-e2e`, and
`make validate`. No billed live-provider validation is required for this
implementation; provider-independent scripted RPC fixtures must exercise both
plain final text and empty final text.

## 10. Non-goals

- No controller-generated power-system conclusions.
- No parsing of arbitrary prose to infer numerical truth.
- No automatic claim category inference.
- No retry intended only to persuade a model to call an output tool.
- No movement of the existing release tag as part of this correction.
- No deletion or migration of existing user run data.
