# Non-blocking Answer Audit Design

## Purpose

Keep a submitted answer, its batch JSONL envelope, and the human report aligned even when evidence auditing finds a problem. Auditing reports evidence-integrity findings; it does not erase or replace an answer already produced by `grid_submit_answer`.

## Scope

- Preserve the submitted `answer_output` when the answer-draft structure is readable.
- Convert audit failures into structured diagnostics with a severity (`warning` or `error`).
- Render the same answer in the single-question envelope, incremental batch JSONL, and Markdown report.
- Keep existing cryptographic/current-run evidence checks; no generic model-side tools or simulator-boundary changes.

## Design

### Answer acceptance and audit outcome

`grid_submit_answer` continues to write `answer-draft.json`. Loading the draft separates structural validity from audit validity:

1. Missing/malformed drafts remain execution failures because there is no usable submitted answer.
2. A structurally valid draft always supplies the answer output.
3. Evidence and result-reference verification returns diagnostics instead of raising an execution-ending exception.

Diagnostics distinguish invalid evidence (error) from a misclassified optional result reference (warning). `result_refs` is only meaningful for `result:sha256:` simulation-result artifacts; topology and other network-fact answers may legitimately submit an empty list and use `claim_evidence_refs` alone.

### User-visible synchronization

The single-run envelope remains the source for the accepted answer. Batch reporting records that answer regardless of audit diagnostics. The report displays:

- the submitted answer under “回答”;
- a successful execution status if the run completed;
- an “审计结论” section only when diagnostics exist, including severity, finding, impact, and remediation.

JSONL continues to contain exactly `question_id` and `answer_output`; it is never substituted with an execution-limitation message solely because audit diagnostics exist.

### Failure boundaries

Hard execution failure is reserved for cases where no structurally usable answer is available: missing/malformed answer draft, invalid envelope, subprocess/runtime failure before answer submission, or other run failure unrelated to audit diagnostics. Audit diagnostics do not mutate the submitted text or silently repair references.

## Tests

1. A topology answer with valid network-fact evidence and mistaken `context:`/`asset:` values in `result_refs` returns its submitted answer plus warning diagnostics.
2. An answer with missing, foreign, or tampered claim evidence returns its submitted answer plus error diagnostics.
3. Batch report and JSONL preserve the submitted answer and expose diagnostics rather than mark the question as failed.
4. Existing valid result-linked AC and N-1 cases remain audit-clean.

## Non-goals

- Do not infer whether natural-language claims are true.
- Do not silently rewrite model-provided references.
- Do not weaken validation of actual `result:sha256:` artifacts or evidence cryptographic integrity.
