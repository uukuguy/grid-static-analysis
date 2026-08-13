# Non-blocking Answer Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a structurally submitted answer in the CLI envelope, JSONL, and report while turning audit failures into durable diagnostics.

**Architecture:** Split answer-draft parsing from audit verification in `grid_agent.cli.app`. Persist `answer-audit.json` beside `answer-draft.json`; the run envelope uses the parsed answer and reporting renders persisted diagnostics without changing an otherwise completed run's status.

**Tech Stack:** Python 3.12, Typer, pytest, existing JSON run artifacts.

## Global Constraints

- stdout remains exactly one JSON envelope with `question_id` and `answer_output`.
- Grid facts remain simulator-backed through `gridctl` capability protocol 1.0 and pandapower 3.4.0.
- Preserve model-submitted answers and references; never silently repair references.
- Audit findings must not turn a structurally valid answer into an execution-limitation envelope.
- Keep unrelated worktree changes intact.

---

### Task 1: Make draft auditing non-blocking

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py:178-200`
- Modify: `packages/grid-agent/tests/cli/test_app.py:1-375`

**Interfaces:**
- Produce `AuditDiagnostic(severity: Literal["warning", "error"], finding: str, impact: str, remediation: str)`.
- Produce `SubmittedAnswer(answer_output: str, diagnostics: tuple[AuditDiagnostic, ...])` from `_load_submitted_answer(workspace: RunWorkspace)`.
- Persist `answer-audit.json` as `{"diagnostics": [{"severity", "finding", "impact", "remediation"}]}`.

- [ ] **Step 1: Write failing tests**

  Add `test_submitted_topology_answer_keeps_answer_and_reports_non_result_references`. Build a current-run network-fact evidence document, submit `answer_output="线路 11 连接母线 6 与 11。"`, valid `claim_evidence_refs`, and `result_refs` containing one `context:sha256:` plus one `asset:line:sha256:`. Assert the returned answer is unchanged, there are two `warning` diagnostics, and persisted `answer-audit.json` contains those warnings.

  Add `test_submitted_answer_keeps_answer_when_claim_evidence_is_foreign`. Submit `answer_output="模型已提交的答案"`, an unknown `evidence:sha256:` reference, and empty `result_refs`. Assert the answer is unchanged and the diagnostic severity is `error`.

- [ ] **Step 2: Verify RED**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py -q -k 'submitted_topology or submitted_answer_keeps'
  ```

  Expected: collection fails because `_load_submitted_answer` and its result types do not exist.

- [ ] **Step 3: Implement the minimal boundary**

  Replace `_load_verified_answer_draft` with draft parsing that keeps hard failures only for missing, malformed, or structurally invalid drafts. Use existing `_verify_evidence_refs`, `_verify_result_refs`, and `_verify_result_evidence_links` unchanged inside `_audit_answer_draft`; catch their `RuntimeError` values and convert them to diagnostics.

  References in `result_refs` that do not start with `result:sha256:` must produce `warning` diagnostics and must not be sent to `_verify_result_refs`. Invalid claim evidence and invalid `result:sha256:` result documents must produce `error` diagnostics. Write all diagnostics atomically to `answer-audit.json`; do not rewrite the draft.

  Update `run()` to create `AnswerEnvelope(question_id=request.question_id, answer_output=submitted.answer_output)` and return successfully when only audit diagnostics exist.

- [ ] **Step 4: Verify GREEN**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py -q -k 'submitted_topology or submitted_answer_keeps or accepts_topology'
  ```

  Expected: selected tests pass.

- [ ] **Step 5: Commit**

  ```sh
  git add packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py
  git commit -m "fix: make answer audit non-blocking"
  ```

### Task 2: Synchronize report and JSONL with the accepted answer

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/reporting.py:45-180`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py:130-155,467-505`
- Modify: `packages/grid-agent/tests/reporting/test_batch_report.py:1-180`

**Interfaces:**
- Add reporting-local immutable `AuditDiagnostic` and `read_answer_audit(run_path: Path) -> tuple[AuditDiagnostic, ...]`.
- Extend `BatchRecord` with `audit_diagnostics: tuple[AuditDiagnostic, ...] = ()`.
- A zero-exit child with diagnostics remains `status="success"` and its answer remains the JSONL answer.

- [ ] **Step 1: Write failing report test**

  Replace the rejection-only rendering test with a `BatchRecord` whose answer is `线路11连接母线6与11。`, status is `success`, and `audit_diagnostics` contains a warning. Assert Markdown contains the answer, `状态：成功`, `审计结论`, and `warning`; assert it does not contain `不能作为最终提交结果`. Write the same record through `write_jsonl` and assert its envelope preserves that answer exactly.

- [ ] **Step 2: Verify RED**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/reporting/test_batch_report.py -q
  ```

  Expected: failure because `BatchRecord` lacks `audit_diagnostics` and the renderer only supports rejection wording.

- [ ] **Step 3: Implement report synchronization**

  `read_answer_audit` must return one error diagnostic when an audit file is malformed instead of breaking report generation. In `report()`, read diagnostics from the child run directory, retain `status="success"` for a zero exit, and pass the diagnostics to `BatchRecord`.

  Render the accepted `answer_output` once. When diagnostics exist, render “审计结论” with severity, finding, impact, and remediation. Remove “未采纳草稿” wording from audit-only paths. Do not alter `write_jsonl` or `append_jsonl_record`: they already serialize `record.answer_output`.

- [ ] **Step 4: Verify GREEN**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/reporting/test_batch_report.py -q
  ```

  Expected: all reporting tests pass.

- [ ] **Step 5: Commit**

  ```sh
  git add packages/grid-agent/src/grid_agent/reporting.py packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/reporting/test_batch_report.py
  git commit -m "fix: report audit findings without rejecting answers"
  ```

### Task 3: Lock the batch regression and run supported verification

**Files:**
- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py` only if its fixtures need no production changes.

**Interfaces:**
- Scripted Pi submits valid topology evidence with mistaken `context:`/`asset:` result references.
- Expected outcome: exit code 0, submitted envelope answer, persisted warnings, matching report/JSONL answer.

- [ ] **Step 1: Write failing end-to-end regression**

  Following existing scripted Pi fixture conventions, submit:

  ```python
  draft = {
      "answer_output": "线路11连接母线6与11。",
      "result_refs": [opened["context_ref"], "asset:line:sha256:" + "a" * 64],
      "claim_evidence_refs": [ref],
  }
  ```

  Assert run exit code is 0, stdout's `AnswerEnvelope.answer_output` is the submitted answer, `answer-audit.json` has two warnings, and report/JSONL have that same answer.

- [ ] **Step 2: Verify RED**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q -k non_blocking_audit
  ```

  Expected: failure before Tasks 1 and 2 are integrated because the run exits non-zero or audit output is absent.

- [ ] **Step 3: Make only fixture/harness changes required by the test**

  Do not loosen simulator evidence generation, Pi tool exposure, or result-document integrity checks. Adjust only test plumbing necessary to drive the implemented run/report path.

- [ ] **Step 4: Verify focused and full gates**

  Run:

  ```sh
  uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/reporting/test_batch_report.py packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q
  make test
  make test-e2e
  make validate
  ```

  Expected: every command exits 0; the regression proves audit findings no longer replace a submitted answer.

- [ ] **Step 5: Commit**

  ```sh
  git add packages/grid-agent/tests/e2e/test_semantic_pi_path.py packages/grid-agent/tests/cli/test_app.py
  git commit -m "test: cover non-blocking answer audit"
  ```
