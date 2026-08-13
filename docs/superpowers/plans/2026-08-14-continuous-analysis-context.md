# Continuous Analysis Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace subprocess-per-question reporting with one continuous Analysis run whose verified simulator state is recorded in a replayable context ledger and rendered as one self-contained report.

**Architecture:** Introduce focused `grid_agent.analysis` components for workspace layout, typed state, pure reduction, durable storage, gridctl artifact admission, semantic tool projection, bounded agent context, turn isolation, orchestration, and reporting. One Pi RPC process handles every ordered instruction; a controller-owned ledger and snapshot—not model prose—carry verified results across turns.

**Tech Stack:** Python 3.12+, Pydantic 2.12, Typer, standard-library JSON/hashlib/pathlib/fsync, Pi RPC JSONL, Node.js domain-tools extension, grid-capability protocol 1.0, pandapower 3.4.0, pytest 9, Node test runner.

## Global Constraints

- `grid-agent` stdout is exactly one JSON object with `question_id` and `answer_output`; progress and diagnostics go to stderr.
- All numerical or network-specific claims cross `gridctl` using `grid-capability` protocol `1.0` and pandapower `3.4.0`.
- Pi may use only project-defined grid tools, `grid_guide_open`, `grid_analysis_context_get`, and `grid_submit_answer`.
- No shell, generic file tools, arbitrary Python, raw pandapower objects, or legacy query aliases are exposed to the model.
- One Analysis invocation uses one Pi process, one Pi session, one workspace, and strictly sequential instructions.
- Named sessions, pause/resume, session switching, cross-run reuse, and concurrent turns remain out of scope.
- The model cannot mutate authoritative context; verified state is projected only from controller events and gridctl artifacts.
- Answer audit is advisory and cannot rewrite or reject a structurally usable submitted answer.
- A successful gridctl response whose claimed content-addressed artifact fails integrity is terminal before another instruction starts.
- Standard traces omit token/reasoning deltas and repeated message snapshots.
- Existing `grid-agent run`, historical `runs/`, and user-owned `var/` data remain untouched.
- Use `apply_patch` for source edits, run focused tests before broad gates, and commit each completed task atomically.

## File Map

### New production modules

- `packages/grid-agent/src/grid_agent/analysis/workspace.py` — self-contained Analysis directory creation and copied-input identity.
- `packages/grid-agent/src/grid_agent/analysis/models.py` — Pydantic state, event, record, diagnostic, and turn models.
- `packages/grid-agent/src/grid_agent/analysis/reducer.py` — pure event-to-context transitions and canonical state hashing.
- `packages/grid-agent/src/grid_agent/analysis/store.py` — append/fsync ledger, atomic snapshot, replay, and consistency checks.
- `packages/grid-agent/src/grid_agent/analysis/integrity.py` — shared context/result/evidence content-reference verification and answer-audit primitives.
- `packages/grid-agent/src/grid_agent/analysis/projector.py` — semantic grid-tool event admission, observation/result/evidence/fact projection, and terminal integrity classification.
- `packages/grid-agent/src/grid_agent/analysis/view.py` — bounded read-only context view injected into later turns.
- `packages/grid-agent/src/grid_agent/analysis/turns.py` — active-turn nonce, draft isolation, archival, JSONL checkpointing, and turn finalization.
- `packages/grid-agent/src/grid_agent/analysis/runner.py` — one-process sequential orchestration and terminal/non-terminal failure policy.
- `packages/grid-agent/src/grid_agent/analysis/report.py` — Analysis report projection and atomic checkpoints.
- `scripts/update_analysis_context_schemas.py` — reproducibly materialize the two normative JSON Schemas from Pydantic models.
- `schemas/analysis-context-v1.schema.json` — checked-in state schema.
- `schemas/analysis-context-event-v1.schema.json` — checked-in committed-event schema.
- `docs/architecture/analysis-context.md` — maintained semantic contract and worked examples.

### Modified production modules

- `packages/grid-agent/src/grid_agent/application/workspace.py` — retain `RunWorkspace`; no Analysis behavior is added here.
- `packages/grid-agent/src/grid_agent/runtime/environment.py` — optional active-turn and context-view paths for Analysis launches.
- `packages/grid-agent/src/grid_agent/runtime/rpc.py` — semantic-event callback, stable tool-call identity, and compact standard tracing.
- `packages/grid-agent/src/grid_agent/cli/app.py` — delegate the new `analysis` command, compatibility `report`, and existing answer audit to focused modules.
- `packages/grid-agent/src/grid_agent/reporting.py` — keep legacy helpers needed by `run`; remove batch-only ownership after migration.
- `packages/pi-grid-tools/src/domain-tools.mjs` — read-only context tool and turn-bound answer submission.
- `Makefile` — canonical `analysis` target and `report` compatibility alias.
- `docs/RUNBOOK.md` and `docs/MANUAL-VALIDATION.md` — operator usage and artifact inspection.

### New and modified tests

- `packages/grid-agent/tests/analysis/test_workspace.py`
- `packages/grid-agent/tests/analysis/test_reducer.py`
- `packages/grid-agent/tests/analysis/test_store.py`
- `packages/grid-agent/tests/analysis/test_integrity.py`
- `packages/grid-agent/tests/analysis/test_projector.py`
- `packages/grid-agent/tests/analysis/test_view.py`
- `packages/grid-agent/tests/analysis/test_turns.py`
- `packages/grid-agent/tests/analysis/test_runner.py`
- `packages/grid-agent/tests/analysis/test_report.py`
- `packages/grid-agent/tests/contract/test_analysis_context_docs.py`
- `packages/grid-agent/tests/runtime/test_rpc.py`
- `packages/grid-agent/tests/runtime/test_pi_config.py`
- `packages/grid-agent/tests/cli/test_app.py`
- `packages/grid-agent/tests/e2e/test_continuous_analysis.py`
- `packages/pi-grid-tools/test/domain-tools.test.mjs`

---

### Task 1: Self-contained Analysis workspace

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/__init__.py`
- Create: `packages/grid-agent/src/grid_agent/analysis/workspace.py`
- Create: `packages/grid-agent/tests/analysis/__init__.py`
- Create: `packages/grid-agent/tests/analysis/test_workspace.py`

**Interfaces:**
- Consumes: `Path`, SHA-256, UTC timestamps.
- Produces: `CopiedInstructions` and `AnalysisWorkspace.create(root: Path, analysis_id: str | None = None) -> AnalysisWorkspace`.
- Produces paths used by all later tasks: `manifest_path`, `copied_instructions_path`, `answers_path`, `report_path`, `context_snapshot_path`, `context_events_path`, `trace_path`, `turns_path`, `evidence_path`, `results_path`, `tool_results_path`, `bin_path`, `pi_path`, `active_turn_path`, `active_answer_draft_path`, and `context_view_path`.

- [ ] **Step 1: Write failing workspace tests**

```python
from hashlib import sha256
from pathlib import Path

import pytest

from grid_agent.analysis.workspace import AnalysisWorkspace


def test_analysis_workspace_creates_one_complete_run_tree(tmp_path: Path) -> None:
    source = tmp_path / "task.md.txt"
    source.write_text("第一条指令\n第二条指令\n", encoding="utf-8")
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")

    copied = workspace.copy_instructions(source)

    assert workspace.root_path == tmp_path / "runs/analysis-test"
    assert workspace.copied_instructions_path.read_bytes() == source.read_bytes()
    assert copied.sha256 == sha256(source.read_bytes()).hexdigest()
    assert copied.instruction_count == 2
    assert workspace.report_path == workspace.root_path / "report.md"
    assert workspace.answers_path == workspace.root_path / "output/answers.jsonl"
    assert workspace.context_snapshot_path == workspace.root_path / "context/analysis-context.json"
    assert workspace.context_events_path == workspace.root_path / "context/context-events.jsonl"
    for path in (workspace.turns_path, workspace.evidence_path, workspace.results_path, workspace.pi_path):
        assert path.is_dir()


def test_copy_instructions_rejects_a_second_different_source(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("一\n", encoding="utf-8")
    second.write_text("二\n", encoding="utf-8")
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    workspace.copy_instructions(first)

    with pytest.raises(RuntimeError, match="already contains copied instructions"):
        workspace.copy_instructions(second)
```

- [ ] **Step 2: Run the tests and confirm the import fails**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'grid_agent.analysis'`.

- [ ] **Step 3: Implement the focused workspace type**

```python
@dataclass(frozen=True, slots=True)
class CopiedInstructions:
    source_path: str
    copied_path: str
    sha256: str
    instruction_count: int


@dataclass(frozen=True, slots=True)
class AnalysisWorkspace:
    analysis_id: str
    root_path: Path
    manifest_path: Path
    copied_instructions_path: Path
    answers_path: Path
    report_path: Path
    context_snapshot_path: Path
    context_events_path: Path
    trace_path: Path
    turns_path: Path
    evidence_path: Path
    results_path: Path
    tool_results_path: Path
    bin_path: Path
    pi_path: Path
    active_turn_path: Path
    active_answer_draft_path: Path
    context_view_path: Path

    def turn_path(self, ordinal: int) -> Path:
        path = self.turns_path / f"{ordinal:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path
```

Add `AnalysisWorkspace.create(root: Path, analysis_id: str | None = None) -> AnalysisWorkspace` with an `analysis-YYYYMMDDTHHMMSSZ` default, explicit subdirectories, and `mkdir(parents=True, exist_ok=False)` for a new analysis root. Add `copy_instructions(source: Path) -> CopiedInstructions` with byte-preserving copy, `load_questions`-equivalent instruction counting, SHA-256, fsync, and rejection when the destination already contains different bytes.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_workspace.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis packages/grid-agent/tests/analysis
git commit -m "feat: add self-contained analysis workspace"
```

### Task 2: Typed context state and pure reducer

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/models.py`
- Create: `packages/grid-agent/src/grid_agent/analysis/reducer.py`
- Create: `packages/grid-agent/tests/analysis/test_reducer.py`

**Interfaces:**
- Consumes: `CopiedInstructions` metadata and controller event payloads.
- Produces: `AnalysisContext`, `AnalysisContextEvent`, `ContextEventDraft`, record models, `initial_context(analysis_id, input_payload, runtime_payload)`, `reduce_context(state, draft)`, and `canonical_state_hash(state)`.
- Invariant: `reduce_context` is pure; it does no filesystem access and admits no model-authored verified facts.

- [ ] **Step 1: Write failing reducer tests**

```python
from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.reducer import canonical_state_hash, initial_context, reduce_context


def test_context_reducer_registers_baseline_result_and_cross_turn_consumption() -> None:
    state = initial_context(
        analysis_id="analysis-test",
        input_payload={"copied_path": "input/instructions.md.txt", "source_path": "task.txt", "sha256": "a" * 64, "instruction_count": 2},
        runtime_payload={"provider": "test", "model": "scripted", "grid_capability_protocol": "1.0", "pandapower_version": "3.4.0"},
    )
    state = reduce_context(state, ContextEventDraft(event_type="turn.started", turn_id="analysis-test-t001", payload={"ordinal": 1, "instruction": "运行潮流", "instruction_sha256": "b" * 64, "nonce_sha256": "c" * 64}))
    state = reduce_context(state, ContextEventDraft(event_type="simulator.context.opened", turn_id="analysis-test-t001", capability="context.open", payload=BASELINE))
    state = reduce_context(state, ContextEventDraft(event_type="result.registered", turn_id="analysis-test-t001", capability="analysis.powerflow.ac.run", payload=RESULT))
    state = reduce_context(state, ContextEventDraft(event_type="turn.completed", turn_id="analysis-test-t001", payload={"status": "success", "answer_path": "turns/001/answer.json", "answer_sha256": "d" * 64, "duration_seconds": 1.5, "consumed_refs": [], "produced_refs": [RESULT_REF]}))
    state = reduce_context(state, ContextEventDraft(event_type="turn.started", turn_id="analysis-test-t002", payload={"ordinal": 2, "instruction": "排序", "instruction_sha256": "e" * 64, "nonce_sha256": "f" * 64}))
    state = reduce_context(state, ContextEventDraft(event_type="tool.observation.recorded", turn_id="analysis-test-t002", capability="result.branches.rank", payload={**RANKING_OBSERVATION, "consumed_refs": [RESULT_REF]}))

    assert state.active_context_ref == CONTEXT_REF
    assert state.results[RESULT_REF].revision_ref == REVISION_REF
    assert state.current_turn.consumed_refs == [RESULT_REF]
    assert state.observations["observation-2"].produced_refs == []
    assert canonical_state_hash(state) == canonical_state_hash(state.model_copy(deep=True))


def test_context_reducer_rejects_result_from_mismatched_revision() -> None:
    state = context_with_baseline()
    bad = ContextEventDraft(event_type="result.registered", turn_id="analysis-test-t001", capability="analysis.powerflow.ac.run", payload={**RESULT, "revision_ref": "revision:sha256:" + "9" * 64})
    with pytest.raises(ContextTransitionError, match="does not match registered baseline"):
        reduce_context(state, bad)
```

Define test constants as complete dictionaries containing valid `context_ref`, `revision_ref`, result/evidence references, solver summary, producer observation, and paths.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q`

Expected: FAIL because `models` and `reducer` do not exist.

- [ ] **Step 3: Implement models and transitions**

Define frozen Pydantic models with `extra="forbid"`:

```python
EventType = Literal[
    "analysis.started", "turn.started", "simulator.context.opened",
    "tool.observation.recorded", "result.registered", "evidence.registered",
    "fact.verified", "tool.failed", "answer.submitted",
    "audit.diagnostic.recorded", "limitation.recorded", "limitation.resolved",
    "turn.completed", "analysis.completed", "analysis.failed",
]

class ContextEventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_type: EventType
    turn_id: str | None = None
    capability: str | None = None
    trace_sequence: int | None = None
    timestamp: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

class AnalysisContextEvent(ContextEventDraft):
    schema_version: Literal["analysis-context-event/1.0"] = "analysis-context-event/1.0"
    analysis_id: str
    sequence: int
    previous_revision: int
    previous_state_hash: str
    next_revision: int
    next_state_hash: str
    integrity: Literal["verified", "diagnostic"]

class AnalysisContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["analysis-context/1.0"] = "analysis-context/1.0"
    analysis_id: str
    revision: int
    state_hash: str
    status: Literal["initializing", "running", "completed", "failed"]
    input: InputRecord
    runtime: RuntimeRecord
    baselines: dict[str, BaselineRecord] = Field(default_factory=dict)
    active_context_ref: str | None = None
    current_turn: ActiveTurn | None = None
    turns: list[TurnRecord] = Field(default_factory=list)
    observations: dict[str, ObservationRecord] = Field(default_factory=dict)
    results: dict[str, ResultRecord] = Field(default_factory=dict)
    evidence: dict[str, EvidenceRecord] = Field(default_factory=dict)
    verified_facts: dict[str, VerifiedFact] = Field(default_factory=dict)
    diagnostics: list[DiagnosticRecord] = Field(default_factory=list)
    unresolved_limitations: list[LimitationRecord] = Field(default_factory=list)
```

Implement explicit transition functions per event type. Reject duplicate active turns, unknown turn completion, reference/baseline mismatch, duplicate identifiers with different content, and completion with an active turn. `canonical_state_hash` must dump with sorted keys and compact separators while excluding the current `state_hash` field.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_reducer.py -q`

Expected: all reducer tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/models.py packages/grid-agent/src/grid_agent/analysis/reducer.py packages/grid-agent/tests/analysis/test_reducer.py
git commit -m "feat: model deterministic analysis context"
```

### Task 3: Durable ledger, replay, and normative schemas

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/store.py`
- Create: `packages/grid-agent/tests/analysis/test_store.py`
- Create: `scripts/update_analysis_context_schemas.py`
- Create: `schemas/analysis-context-v1.schema.json`
- Create: `schemas/analysis-context-event-v1.schema.json`
- Create: `packages/grid-agent/tests/contract/test_analysis_context_docs.py`

**Interfaces:**
- Consumes: `AnalysisWorkspace`, `AnalysisContext`, `ContextEventDraft`, `reduce_context`.
- Produces: `AnalysisContextStore.initialize(workspace, input_record, runtime_record)`, `.append(draft, integrity)`, `.snapshot`, `.replay(ledger_path)`, and `.verify_materialized_snapshot()`.
- Invariant: ledger append and fsync occur before atomic snapshot replacement.

- [ ] **Step 1: Write failing persistence and schema-sync tests**

```python
def test_store_replays_ledger_to_identical_snapshot(tmp_path: Path) -> None:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    first = store.append(ContextEventDraft(event_type="turn.started", turn_id="analysis-test-t001", payload=TURN_START))
    second = store.append(ContextEventDraft(event_type="turn.completed", turn_id="analysis-test-t001", payload=TURN_COMPLETE))

    replayed = AnalysisContextStore.replay(workspace.context_events_path)

    assert first.sequence == 2  # analysis.started is sequence 1
    assert second.previous_state_hash == first.next_state_hash
    assert replayed == store.snapshot
    assert json.loads(workspace.context_snapshot_path.read_text(encoding="utf-8")) == store.snapshot.model_dump(mode="json")


def test_checked_in_schemas_match_pydantic_models() -> None:
    root = Path(__file__).resolve().parents[4]
    assert json.loads((root / "schemas/analysis-context-v1.schema.json").read_text()) == AnalysisContext.model_json_schema()
    assert json.loads((root / "schemas/analysis-context-event-v1.schema.json").read_text()) == AnalysisContextEvent.model_json_schema()
```

Add tests for a truncated final ledger line, a sequence gap, a previous-hash mismatch, and a snapshot modified after replay.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py -q`

Expected: FAIL because the store and schema files do not exist.

- [ ] **Step 3: Implement store and schema generator**

Add `AnalysisContextStore.initialize(workspace, *, input_record, runtime_record)`, read-only `.snapshot`, `.append(draft, *, integrity="verified")`, `.replay(ledger_path)`, and `.verify_materialized_snapshot()` with the exact return types in the Interfaces block. Use private `_append_jsonl_fsync`, `_write_json_atomic`, and canonical JSON helpers. Initialization deterministically builds revision-zero `initializing` state from the supplied analysis ID/input/runtime, then commits `analysis.started` as sequence 1 and revision 1 with status `running`. The first event payload repeats the complete input/runtime records; replay rebuilds the same revision-zero genesis state from that payload, verifies `previous_state_hash`, and applies the event. Reject malformed or non-contiguous events rather than silently skipping them.

```python
def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
```

The schema script imports both Pydantic models and writes `json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"` through atomic replacement.

- [ ] **Step 4: Generate schemas and run focused tests**

Run: `uv run --project packages/grid-agent python scripts/update_analysis_context_schemas.py`

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py -q`

Expected: all tests PASS and a second schema-generation run produces no git diff.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/store.py packages/grid-agent/tests/analysis/test_store.py packages/grid-agent/tests/contract/test_analysis_context_docs.py scripts/update_analysis_context_schemas.py schemas
git commit -m "feat: persist replayable analysis context"
```

### Task 4: Shared content-reference integrity boundary

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/integrity.py`
- Create: `packages/grid-agent/tests/analysis/test_integrity.py`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py`

**Interfaces:**
- Consumes: an analysis/run root and `context:`, `revision:`, `result:`, or `evidence:` references.
- Produces: `ContentReferenceVerifier`, `VerifiedArtifact`, `ReferenceDiagnostic`, `SimulatorIntegrityError`.
- Produces `audit_answer_references(claim_evidence_refs, result_refs) -> tuple[ReferenceDiagnostic, ...]` and `admit_successful_tool_references(capability, result, evidence_refs) -> VerifiedReferenceSet`.
- Invariant: answer audit returns diagnostics; successful gridctl artifact corruption raises `SimulatorIntegrityError`.

- [ ] **Step 1: Write failing integrity-boundary tests**

```python
def test_answer_audit_reports_bad_reference_without_raising(tmp_path: Path) -> None:
    verifier = ContentReferenceVerifier(tmp_path)
    diagnostics = verifier.audit_answer_references(
        claim_evidence_refs=("evidence:sha256:" + "a" * 64,),
        result_refs=("context:sha256:" + "b" * 64,),
    )
    assert {item.category for item in diagnostics} == {"missing_evidence", "misclassified_result_ref"}


def test_successful_gridctl_result_with_tampered_artifact_is_terminal(tmp_path: Path) -> None:
    result_ref = write_valid_result(tmp_path, context_ref=CONTEXT_REF, revision_ref=REVISION_REF)
    result_path(tmp_path, result_ref).write_text('{"tampered":true}', encoding="utf-8")
    verifier = ContentReferenceVerifier(tmp_path)

    with pytest.raises(SimulatorIntegrityError, match="digest"):
        verifier.admit_successful_tool_references(
            capability="analysis.powerflow.ac.run",
            result={"context_ref": CONTEXT_REF, "revision_ref": REVISION_REF, "result_ref": result_ref},
            evidence_refs=(),
        )
```

Port the existing valid topology, AC, aggregate N-1, missing/foreign, tampered, and misclassified-result cases from `tests/cli/test_app.py` to the new module. Retain CLI-level tests proving answer text is preserved.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_integrity.py packages/grid-agent/tests/cli/test_app.py -q`

Expected: FAIL because `ContentReferenceVerifier` is absent.

- [ ] **Step 3: Extract verification without weakening current behavior**

```python
@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    reference: str
    kind: Literal["context", "result", "evidence"]
    document: Mapping[str, Any]
    path: Path

@dataclass(frozen=True, slots=True)
class VerifiedReferenceSet:
    context: tuple[VerifiedArtifact, ...] = ()
    results: tuple[VerifiedArtifact, ...] = ()
    evidence: tuple[VerifiedArtifact, ...] = ()

class SimulatorIntegrityError(RuntimeError):
    pass

class SimulatorIntegrityError(RuntimeError):
    """A successful simulator response cannot be trusted for a later turn."""
```

Add `ContentReferenceVerifier(workspace_root)`, `verify_context(reference)`, `verify_result(reference)`, `verify_evidence(reference)`, `audit_answer_references(claim_evidence_refs, result_refs)`, and `admit_successful_tool_references(capability, result, evidence_refs)` with the exact types in the Interfaces block. Move canonical JSON digest verification, current-workspace path resolution, self-reference checks, context/revision linkage, and aggregate scenario traversal from `cli/app.py`. Keep thin compatibility wrappers while existing tests migrate. Do not make answer-link adequacy a prerequisite for context admission.

- [ ] **Step 4: Run focused and legacy audit tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_integrity.py packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q`

Expected: all tests PASS; the existing non-blocking audit E2E still preserves the submitted answer.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/integrity.py packages/grid-agent/tests/analysis/test_integrity.py packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py
git commit -m "refactor: share analysis reference verification"
```

### Task 5: Compact semantic RPC events

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/runtime/rpc.py`
- Modify: `packages/grid-agent/tests/runtime/test_rpc.py`

**Interfaces:**
- Consumes: raw Pi RPC events.
- Produces: `SemanticEventCallback = Callable[[dict[str, Any]], None]` through the `on_semantic_event` keyword of `prompt_and_wait`.
- Produces normalized `tool_execution_start`, `tool_result`, `assistant_message`, acknowledgement, and `agent_end` events.
- Invariant: standard trace excludes `text_delta`, reasoning deltas, and growing `message_update` snapshots.

- [ ] **Step 1: Add failing semantic-trace tests**

```python
def test_rpc_emits_semantic_tools_and_omits_streaming_snapshots(tmp_path: Path) -> None:
    client, workspace = scripted_rpc_client(tmp_path, events=[
        {"type": "response", "command": "prompt", "success": True},
        {"type": "text_delta", "text": "答"},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "案"}},
        {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "grid_context_open", "args": {"model_id": "ieee39"}},
        successful_tool_end("call-1", "grid_context_open", "context.open", OPEN_RESULT),
        {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "答案"}]}]},
    ])
    semantic = []
    client.start()
    try:
        assert client.prompt_and_wait("question", on_semantic_event=semantic.append) == "答案"
    finally:
        client.stop()

    traced = [json.loads(line)["payload"] for line in workspace.events_path.read_text().splitlines()]
    assert any(item.get("type") == "tool_execution_start" and item["tool_call_id"] == "call-1" for item in semantic)
    assert any(item.get("event") == "tool_result" and item["tool_call_id"] == "call-1" for item in semantic)
    assert not any(item.get("type") in {"text_delta", "message_update"} for item in traced)
    assert not any("messages" in item for item in traced)
```

Retain separate tests that streamed deltas still assemble the returned public answer text even though they are not traced.

- [ ] **Step 2: Run and confirm current trace is too verbose**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py -q`

Expected: the new omission assertion FAILS because `_skip_trace_event` currently always returns `False`.

- [ ] **Step 3: Implement semantic normalization and filtering**

```python
SemanticEventCallback = Callable[[dict[str, Any]], None]

TRACEABLE_RPC_TYPES = frozenset({"prompt_ack", "response", "tool_execution_start", "tool_execution_end", "agent_end"})

def _skip_trace_event(event: dict[str, Any]) -> bool:
    return event.get("type") not in TRACEABLE_RPC_TYPES
```

Extend `prompt_and_wait` with `on_semantic_event: SemanticEventCallback | None = None` immediately after `on_event`. Normalize tool-call IDs and tool names onto canonical start/end events. Replace raw trace append with `_semantic_trace_payload(event, assembled_public_text)`: acknowledgement keeps only `type`, `command`, `success`, and `ok`; tool start keeps call ID/name/arguments; tool end becomes the existing canonical tool result; `agent_end` keeps only `type` and public stop status; one separate `assistant_message` record contains the assembled public answer. Do not persist the raw `agent_end.messages` array because it can contain the entire conversation or reasoning blocks. Emit the same normalized events through `on_semantic_event`.

- [ ] **Step 4: Run RPC tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/runtime/test_rpc.py packages/grid-agent/tests/test_trace.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/runtime/rpc.py packages/grid-agent/tests/runtime/test_rpc.py
git commit -m "feat: record compact semantic pi traces"
```

### Task 6: Tool-result projector and verified fact promotion

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/projector.py`
- Create: `packages/grid-agent/tests/analysis/test_projector.py`

**Interfaces:**
- Consumes: normalized semantic tool starts/results, `ContentReferenceVerifier`, `AnalysisContextStore`.
- Produces: `AnalysisContextProjector.observe(event: Mapping[str, Any], *, turn_id: str) -> None`.
- Invariant: only the explicit projection allowlist creates verified facts; large result bodies remain in artifacts.

- [ ] **Step 1: Write failing projection tests**

```python
def test_projector_registers_powerflow_and_ranking_dependency(context_harness) -> None:
    projector = context_harness.projector
    projector.observe(tool_start("call-1", "grid_analysis_powerflow_ac", {"context_ref": CONTEXT_REF}), turn_id="analysis-test-t001")
    projector.observe(tool_result("call-1", "analysis.powerflow.ac.run", POWERFLOW_RESULT), turn_id="analysis-test-t001")
    projector.observe(tool_start("call-2", "grid_result_branches_rank", {"result_ref": RESULT_REF, "metric": "loading_percent", "limit": 5}), turn_id="analysis-test-t002")
    projector.observe(tool_result("call-2", "result.branches.rank", RANK_RESULT), turn_id="analysis-test-t002")

    state = context_harness.store.snapshot
    assert RESULT_REF in state.results
    ranking = next(item for item in state.observations.values() if item.capability == "result.branches.rank")
    assert ranking.consumed_refs == [RESULT_REF]
    assert ranking.produced_refs == []
    assert any(fact.predicate == "branch.loading_percent" and fact.source_observation_id == ranking.observation_id for fact in state.verified_facts.values())


def test_projector_stops_on_integrity_failure_but_records_normal_tool_error(context_harness) -> None:
    context_harness.projector.observe(tool_result("call-1", "analysis.powerflow.ac.run", {}, ok=False, error={"code": "powerflow_non_convergence"}), turn_id="analysis-test-t001")
    assert context_harness.store.snapshot.unresolved_limitations
    with pytest.raises(SimulatorIntegrityError):
        context_harness.projector.observe(tool_result("call-2", "analysis.powerflow.ac.run", TAMPERED_RESULT), turn_id="analysis-test-t001")
```

Add topology endpoint, context.open, N-1 aggregate/scenario, duplicate reference, unknown-field, and mismatched-baseline cases.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py -q`

Expected: FAIL because the projector does not exist.

- [ ] **Step 3: Implement deterministic projection**

Add `AnalysisContextProjector(store: AnalysisContextStore, verifier: ContentReferenceVerifier)` with a private `dict[str, Mapping[str, Any]]` start-event registry and `observe(event: Mapping[str, Any], *, turn_id: str) -> None`. Use tool-call ID to pair actual inputs with results. For every result, append `tool.observation.recorded`; then append separate baseline, result, evidence, fact, limitation, or diagnostic events in deterministic order. Promote only:

```python
PROMOTED_FACT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "topology.branch.endpoints.get": ("from_bus", "to_bus"),
    "analysis.powerflow.ac.run": ("converged", "total_active_loss"),
    "result.branches.rank": ("branches",),
    "analysis.contingency.n_minus_one.run": ("status", "scenarios"),
}
```

- topology `from_bus`/`to_bus` identity;
- AC `converged` and `total_active_loss`;
- ranking branch metric values and units;
- N-1 aggregate status, scenario count, scenario maximum loading, and violation count.

Every promoted fact includes `context_ref`, `revision_ref`, producer observation, turn, and source `result_ref` or `evidence_ref`.

- [ ] **Step 4: Run projection, reducer, and integrity tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_projector.py packages/grid-agent/tests/analysis/test_reducer.py packages/grid-agent/tests/analysis/test_integrity.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/projector.py packages/grid-agent/tests/analysis/test_projector.py
git commit -m "feat: project verified grid analysis state"
```

### Task 7: Bounded context view and turn-bound domain tools

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/view.py`
- Create: `packages/grid-agent/tests/analysis/test_view.py`
- Modify: `packages/grid-agent/src/grid_agent/runtime/environment.py`
- Modify: `packages/grid-agent/tests/runtime/test_pi_config.py`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/pi-grid-tools/test/domain-tools.test.mjs`

**Interfaces:**
- Consumes: `AnalysisContext`, `active-turn.json`, optional `analysis-context-view.json`.
- Produces: `build_context_view(context: AnalysisContext) -> dict[str, Any]`, `materialize_context_view(context, path)`, and `grid_analysis_context_get`.
- Extends `RuntimePaths` with optional `active_turn_path` and `analysis_context_view_path`.
- Invariant: context tool is read-only and answer drafts are bound to controller turn ID/nonce.

- [ ] **Step 1: Write failing Python and Node tests**

```python
def test_context_view_is_bounded_and_keeps_reusable_provenance(context_with_large_results) -> None:
    view = build_context_view(context_with_large_results)
    encoded = json.dumps(view, ensure_ascii=False)
    assert view["revision"] == context_with_large_results.revision
    assert view["state_hash"] == context_with_large_results.state_hash
    assert view["reusable_results"][0]["result_ref"] == RESULT_REF
    assert view["reusable_results"][0]["evidence_refs"] == [EVIDENCE_REF]
    assert "branch_results" not in encoded
    assert len(encoded.encode("utf-8")) < 64_000
```

```javascript
test("analysis tools expose bounded context and bind answer to active turn", async () => {
  const root = await makeFixtureRoot();
  await configureAnalysisPaths(root, {
    turn_id: "analysis-test-t002",
    turn_nonce: "nonce-2",
  }, { schema_version: "analysis-context-view/1.0", revision: 9, state_hash: "sha256:test" });
  const registered = [];
  domainToolsExtension({ registerTool: (tool) => registered.push(tool) });

  const context = await registered.find((tool) => tool.name === "grid_analysis_context_get").execute("context-1", {});
  const submitted = await registered.find((tool) => tool.name === "grid_submit_answer").execute("submit-1", {
    answer_output: "答案", result_refs: [], claim_evidence_refs: [],
  });

  assert.equal(context.details.result.revision, 9);
  assert.deepEqual(JSON.parse(await readFile(process.env.GRID_AGENT_ANSWER_DRAFT, "utf8")), {
    turn_id: "analysis-test-t002", turn_nonce: "nonce-2",
    answer_output: "答案", result_refs: [], claim_evidence_refs: [],
  });
  assert.equal(submitted.details.result.turn_id, "analysis-test-t002");
});
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_view.py packages/grid-agent/tests/runtime/test_pi_config.py -q && npm test --prefix packages/pi-grid-tools`

Expected: FAIL because the view and Analysis environment variables are absent.

- [ ] **Step 3: Implement view materialization and restricted tools**

Add `build_context_view(context: AnalysisContext) -> dict[str, Any]` and `materialize_context_view(context: AnalysisContext, path: Path) -> None`.

```python
CONTEXT_VIEW_VERSION = "analysis-context-view/1.0"
MAX_VIEW_BYTES = 64_000
MAX_FACTS_PER_PREDICATE = 20
```

The view includes active baseline, completed turn summaries, reusable verified results, compact verified facts, unresolved limitations, revision, and state hash. Sort entries deterministically, cap fact lists per predicate at `MAX_FACTS_PER_PREDICATE`, and raise `ContextViewTooLarge` if the provenance-preserving view exceeds `MAX_VIEW_BYTES` rather than silently truncating identifiers.

In Node, treat both new paths as optional absolute paths confined to `GRID_AGENT_WORKSPACE`. Register `grid_analysis_context_get` only when a context-view path is configured. On every answer submission, read the active-turn file immediately before atomic write and add its exact `turn_id` and `turn_nonce`. Preserve existing single-run behavior when neither Analysis path is configured.

- [ ] **Step 4: Run Python and Node tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_view.py packages/grid-agent/tests/runtime/test_pi_config.py -q`

Run: `npm run check --prefix packages/pi-grid-tools && npm test --prefix packages/pi-grid-tools`

Expected: all tests PASS and the registered Analysis tool set contains no generic filesystem or shell capability.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/view.py packages/grid-agent/tests/analysis/test_view.py packages/grid-agent/src/grid_agent/runtime/environment.py packages/grid-agent/tests/runtime/test_pi_config.py packages/pi-grid-tools/src/domain-tools.mjs packages/pi-grid-tools/test/domain-tools.test.mjs
git commit -m "feat: expose bounded analysis context to pi"
```

### Task 8: Turn isolation, archival, and incremental answers

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/turns.py`
- Create: `packages/grid-agent/tests/analysis/test_turns.py`

**Interfaces:**
- Consumes: `AnalysisWorkspace`, `AnalysisContextStore`, submitted answer draft, non-blocking audit callback.
- Produces: `TurnController.start(ordinal, instruction) -> ActiveTurnHandle`, `.finalize(handle, duration_seconds) -> FinalizedTurn`, and `.fail(handle, error, duration_seconds) -> FinalizedTurn`.
- Invariant: stale drafts cannot satisfy a new turn; accepted answer text is identical in draft, answer JSON, JSONL, and report input.

- [ ] **Step 1: Write failing turn tests**

```python
def test_turn_controller_rejects_stale_draft_and_archives_current_submission(harness) -> None:
    first = harness.turns.start(1, "第一条")
    write_draft(harness.workspace.active_answer_draft_path, first, answer="第一答")
    harness.turns.finalize(first, duration_seconds=1.0)
    second = harness.turns.start(2, "第二条")
    write_raw_draft(harness.workspace.active_answer_draft_path, turn_id=first.turn_id, turn_nonce=first.turn_nonce, answer="旧答")

    with pytest.raises(StaleAnswerDraftError):
        harness.turns.finalize(second, duration_seconds=1.0)

    write_draft(harness.workspace.active_answer_draft_path, second, answer="第二答")
    completed = harness.turns.finalize(second, duration_seconds=1.2)
    assert completed.answer_output == "第二答"
    assert json.loads((harness.workspace.turn_path(2) / "answer.json").read_text())["answer_output"] == "第二答"
    assert [json.loads(line)["answer_output"] for line in harness.workspace.answers_path.read_text().splitlines()] == ["第一答", "第二答"]
```

Add tests for audit diagnostics, no draft (`failed` turn plus limitation), atomic active-turn replacement, and nonce hash—but not raw nonce—in `AnalysisContext`.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py -q`

Expected: FAIL because `TurnController` does not exist.

- [ ] **Step 3: Implement turn lifecycle**

```python
@dataclass(frozen=True, slots=True)
class ActiveTurnHandle:
    ordinal: int
    turn_id: str
    instruction: str
    instruction_sha256: str
    turn_nonce: str
    started_monotonic: float

@dataclass(frozen=True, slots=True)
class FinalizedTurn:
    turn_id: str
    status: Literal["success", "limited", "failed"]
    answer_output: str
    answer_path: Path | None
    audit_diagnostics: tuple[ReferenceDiagnostic, ...]
    error: str | None

```

Add `TurnController.start(ordinal, instruction)`, `.finalize(handle, *, duration_seconds)`, and `.fail(handle, *, error, duration_seconds)` with the exact types in the Interfaces block. Use `secrets.token_urlsafe(32)` for the nonce, store the raw value only in `active-turn.json` and the bound draft, hash it for the context event, clear the draft before every prompt, and append answer envelopes with flush/fsync. Call the shared audit after structural draft validation; archive diagnostics without mutating `answer_output`.

- [ ] **Step 4: Run turn and existing audit tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_turns.py packages/grid-agent/tests/cli/test_app.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/turns.py packages/grid-agent/tests/analysis/test_turns.py
git commit -m "feat: isolate continuous analysis turns"
```

### Task 9: Analysis report driven by structured context

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/report.py`
- Create: `packages/grid-agent/tests/analysis/test_report.py`
- Modify: `packages/grid-agent/src/grid_agent/reporting.py`
- Modify: `packages/grid-agent/tests/reporting/test_batch_report.py`

**Interfaces:**
- Consumes: finalized `AnalysisContext`, turn artifacts, manifest, workspace-relative links.
- Produces: `render_analysis_report(context, workspace, environment) -> str` and `write_analysis_report_checkpoint(context, workspace, environment) -> None`.
- Invariant: baseline appears globally once; each turn shows before/after revisions and actual consumed/produced references.

- [ ] **Step 1: Write failing report tests**

```python
def test_report_renders_baseline_once_and_turn_context_deltas(report_fixture) -> None:
    report = render_analysis_report(
        context=report_fixture.context,
        workspace=report_fixture.workspace,
        environment=report_fixture.environment,
    )
    assert report.count("## 仿真基线") == 1
    assert report.count("pandapower.networks.case39") == 1
    assert "## 分析执行上下文" in report
    assert "上下文版本：5 → 9" in report
    assert "复用前序结果" in report
    assert RESULT_REF in report
    assert "结果依赖关系" in report
    assert "context/analysis-context.json" in report
    assert "context/context-events.jsonl" in report


def test_report_keeps_submitted_answer_when_audit_has_errors(report_fixture) -> None:
    report = render_analysis_report(context=report_fixture.with_audit_error(), workspace=report_fixture.workspace, environment={})
    assert report_fixture.answer_text in report
    assert "审计诊断" in report
    assert "模型草稿（未采纳）" not in report
```

Add tests for failed/limited turns, unresolved limitations, multiple baselines, representative evidence links, no absolute-path leakage, and atomic checkpoint replacement.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py -q`

Expected: FAIL because the Analysis report module does not exist.

- [ ] **Step 3: Implement context-driven rendering**

Add `render_analysis_report(*, context, workspace, environment) -> str` and `write_analysis_report_checkpoint(*, context, workspace, environment) -> None` with the exact types in the Interfaces block.

```python
REPORT_SECTIONS = (
    "分析摘要", "运行环境", "仿真基线", "分析执行上下文",
    "结果依赖关系", "指令执行时间线", "未解决限制", "复核工件",
)
```

Read per-turn accepted answer JSON by the paths registered in context. Render every `REPORT_SECTIONS` entry in that order, omitting only an empty `未解决限制` body. Use workspace-relative Markdown links and do not humanize or rewrite accepted answer text. Leave legacy single-run helpers in `reporting.py` until the CLI migration test proves no batch owner remains.

- [ ] **Step 4: Run new and legacy report tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_report.py packages/grid-agent/tests/reporting/test_batch_report.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/report.py packages/grid-agent/tests/analysis/test_report.py packages/grid-agent/src/grid_agent/reporting.py packages/grid-agent/tests/reporting/test_batch_report.py
git commit -m "feat: render context-driven analysis reports"
```

### Task 10: One-process Analysis runner

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/runner.py`
- Create: `packages/grid-agent/tests/analysis/test_runner.py`

**Interfaces:**
- Consumes: resolved LLM config, Pi launch factory/client, workspace, context store/projector/view, turn controller/report writer.
- Produces: `AnalysisRequest`, `AnalysisOutcome`, `AnalysisRunner.run(request) -> AnalysisOutcome`.
- Invariant: exactly one Pi `start` and `stop`; every next prompt is sent only after prior context/report finalization.

- [ ] **Step 1: Write failing orchestration tests with fakes**

```python
def test_runner_reuses_one_pi_process_and_injects_finalized_prior_context(runner_harness) -> None:
    outcome = runner_harness.runner.run(AnalysisRequest(
        analysis_id="analysis-test",
        instructions=("运行交流潮流", "按负载率排序"),
    ))
    assert runner_harness.pi.start_calls == 1
    assert runner_harness.pi.stop_calls == 1
    assert len(runner_harness.pi.prompts) == 2
    assert "运行交流潮流" in runner_harness.pi.prompts[0]
    assert RESULT_REF in runner_harness.pi.prompts[1]
    assert outcome.status == "completed"
    assert runner_harness.store.snapshot.turns[1].consumed_refs == [RESULT_REF]


def test_runner_continues_after_missing_answer_but_stops_on_integrity_failure(runner_harness) -> None:
    runner_harness.pi.behavior = [NO_DRAFT_AGENT_END, TAMPERED_SUCCESSFUL_RESULT, SHOULD_NOT_RUN]
    outcome = runner_harness.runner.run(AnalysisRequest(analysis_id="analysis-test", instructions=("一", "二", "三")))
    assert len(runner_harness.pi.prompts) == 2
    assert outcome.status == "failed"
    assert runner_harness.store.snapshot.turns[0].status == "failed"
    assert runner_harness.store.snapshot.status == "failed"
```

Add cases for normal gridctl error, provider/Pi death, report checkpoint after each turn, and final replay verification.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis/test_runner.py -q`

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement orchestration with dependency injection**

```python
@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    analysis_id: str
    instructions: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    analysis_id: str
    status: Literal["completed", "failed"]
    report_path: Path
    completed_turns: int
    total_turns: int
    error: str | None = None

```

Add `AnalysisRunner.run(request: AnalysisRequest) -> AnalysisOutcome`. Start Pi once in a `try/finally`. For each instruction: start turn, materialize/inject the latest view, call `prompt_and_wait` with progress plus projector callbacks, finalize or fail the turn, materialize the next view, and checkpoint the report. Missing draft is non-terminal; `PiProtocolError`, durable state failure, and `SimulatorIntegrityError` are terminal. Before successful completion, append `analysis.completed`, replay the ledger, verify the snapshot, then write the final report and manifest status.

- [ ] **Step 4: Run all Analysis unit tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis -q`

Expected: all Analysis tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/runner.py packages/grid-agent/tests/analysis/test_runner.py
git commit -m "feat: run ordered instructions in one pi session"
```

### Task 11: CLI and Makefile migration

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py`
- Modify: `Makefile`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/MANUAL-VALIDATION.md`

**Interfaces:**
- Consumes: `AnalysisWorkspace`, `AnalysisRunner`, existing provider resolution/runtime setup.
- Produces: `grid-agent analysis --instructions PATH`, `make analysis`, and compatibility `grid-agent report --questions PATH` / `make report` delegation.
- Invariant: no child `grid-agent run` subprocess; one stdout envelope only.

- [ ] **Step 1: Write failing CLI contract tests**

```python
def test_analysis_cli_emits_one_envelope_and_uses_self_contained_paths(cli_harness) -> None:
    result = cli_harness.invoke(["analysis", "--instructions", str(cli_harness.instructions)])
    assert result.exit_code == 0
    assert len(result.stdout.splitlines()) == 1
    envelope = AnswerEnvelope.model_validate_json(result.stdout)
    analysis_root = cli_harness.root / "runs" / envelope.question_id
    assert envelope.answer_output == f"runs/{envelope.question_id}/report.md"
    assert (analysis_root / "input/instructions.md.txt").is_file()
    assert (analysis_root / "output/answers.jsonl").is_file()
    assert (analysis_root / "context/analysis-context.json").is_file()


def test_report_command_delegates_to_analysis_without_child_run(cli_harness, monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", fail_if_called)
    result = cli_harness.invoke(["report", "--questions", str(cli_harness.instructions)])
    assert result.exit_code == 0
    assert AnswerEnvelope.model_validate_json(result.stdout).question_id.startswith("analysis-")
```

Use dependency injection/monkeypatching at the runner factory boundary so the test forbids only the former child-run launcher, not the Pi runtime process owned by `PiRpcClient`.

- [ ] **Step 2: Run and confirm current batch contract fails**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py -q`

Expected: FAIL because `analysis` is absent and `report` still emits human stdout plus child runs.

- [ ] **Step 3: Delegate CLI setup and update operator targets**

Add the `analysis` command with `--instructions`, `--artifact-root`, `--provider`, and `--model`; add a compatibility `report` command with `--questions`, `--provider`, and `--model` that calls the same private `_execute_analysis`. Require the resolved artifact root to remain beneath the project root so `answer_output` is always project-relative. Move progress announcements to stderr and emit one `AnswerEnvelope` after runner finalization. Remove obsolete `--output`, `--report-path`, `_run_child_with_live_stderr`, and batch child-boundary code after tests no longer reference them.

Update Makefile:

```make
.PHONY: analysis report
INSTRUCTIONS ?= validation/questions/task.md.txt

analysis:
	@test -f "$(INSTRUCTIONS)" || (echo "Instruction file not found: $(INSTRUCTIONS)" >&2; exit 2)
	uv run --project packages/grid-agent grid-agent analysis --instructions "$(INSTRUCTIONS)" $(if $(PROVIDER),--provider "$(PROVIDER)") $(if $(MODEL),--model "$(MODEL)")

report: analysis
```

Document the compatibility alias, single directory, stdout/stderr behavior, and absence of resume/session switching.

- [ ] **Step 4: Run CLI, Makefile help, and offline contract tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/cli/test_app.py packages/grid-agent/tests/test_console_target.py packages/grid-agent/tests/test_contracts.py -q`

Run: `make help`

Expected: tests PASS; help lists `make analysis` as canonical and `make report` as compatibility alias.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py Makefile docs/RUNBOOK.md docs/MANUAL-VALIDATION.md
git commit -m "feat: make analysis the continuous report workflow"
```

### Task 12: Maintained architecture contract and continuous E2E

**Files:**
- Create: `docs/architecture/analysis-context.md`
- Modify: `packages/grid-agent/tests/contract/test_analysis_context_docs.py`
- Create: `packages/grid-agent/tests/e2e/test_continuous_analysis.py`
- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`

**Interfaces:**
- Consumes: public CLI, schemas, Analysis artifacts, scripted Pi, real workspace-local gridctl.
- Produces: one acceptance scenario proving result reuse, context flow, report alignment, and compact traces.

- [ ] **Step 1: Write failing contract and E2E tests**

```python
def test_architecture_doc_names_every_normative_event_and_schema() -> None:
    root = Path(__file__).resolve().parents[4]
    text = (root / "docs/architecture/analysis-context.md").read_text(encoding="utf-8")
    assert "schemas/analysis-context-v1.schema.json" in text
    assert "schemas/analysis-context-event-v1.schema.json" in text
    for event_type in get_args(EventType):
        assert f"`{event_type}`" in text
```

```python
def test_continuous_analysis_reuses_powerflow_result_and_reports_context_lineage(scripted_analysis) -> None:
    completed = scripted_analysis.run(("运行交流潮流", "筛选负载率最高的5条线路", "对最高负载线路开展N-1校核"))
    assert completed.returncode == 0, completed.stderr
    envelope = AnswerEnvelope.model_validate_json(completed.stdout)
    root = scripted_analysis.project_root / "runs" / envelope.question_id
    answers = [json.loads(line) for line in (root / "output/answers.jsonl").read_text().splitlines()]
    context = AnalysisContext.model_validate_json((root / "context/analysis-context.json").read_text())
    trace = [json.loads(line) for line in (root / "trace/events.jsonl").read_text().splitlines()]

    assert len(answers) == 3
    assert scripted_analysis.pi_process_start_count == 1
    powerflow_ref = next(iter(context.results))
    ranking = next(item for item in context.observations.values() if item.capability == "result.branches.rank")
    assert ranking.consumed_refs == [powerflow_ref]
    assert context.turns[2].consumed_refs
    assert "上下文版本" in (root / "report.md").read_text(encoding="utf-8")
    assert not any(item["payload"].get("type") in {"text_delta", "message_update"} for item in trace)
    assert AnalysisContextStore.replay(root / "context/context-events.jsonl") == context
```

The scripted Pi must read multiple prompt lines from one process, call actual `gridctl` capabilities, reuse the exact prior `result_ref` in the second prompt, submit turn-bound drafts, and select an actual branch reference from the ranking before the N-1 call.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/contract/test_analysis_context_docs.py packages/grid-agent/tests/e2e/test_continuous_analysis.py -q`

Expected: FAIL until the maintained architecture document and scripted multi-prompt fixture exist.

- [ ] **Step 3: Write the maintained contract and scripted acceptance fixture**

The architecture document must contain these complete sections:

```markdown
# Analysis Context Architecture

## Ownership Boundaries
## State and Event Schemas
## Lifecycle and State Machine
## Event-to-State Reduction Rules
## Content Integrity and Failure Boundaries
## Model-facing Context View
## Report Projection
## Schema Evolution Rules
## Topology Example
## AC Power Flow and Ranking Example
## N-1 Example
```

For each worked example, show the concrete capability input, emitted context event types, registered references, promoted fact shape, and report projection. State that compatible additions require optional fields or a new schema version; incompatible changes require `analysis-context/2.0` and a new schema file.

Implement the scripted Pi as a generated executable fixture that loops over stdin until EOF, persists a process-start marker once, reads `GRID_AGENT_ANALYSIS_CONTEXT_VIEW` before prompts 2 and 3, and emits current Pi RPC `tool_execution_start`/`tool_execution_end` events with stable tool-call IDs.

- [ ] **Step 4: Run focused E2E and complete repository gates**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/contract/test_analysis_context_docs.py packages/grid-agent/tests/e2e/test_continuous_analysis.py packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q`

Expected: all focused tests PASS.

Run: `make doctor`

Expected: exits 0 and reports the resolved gridctl path.

Run: `make test`

Expected: agent, simulator, and Node suites all PASS.

Run: `make test-e2e`

Expected: all offline/scripted E2E tests PASS.

Run: `make validate`

Expected: deterministic offline and scripted validation suites PASS. Do not run `make validate-provider` without explicit provider credentials and authorization.

- [ ] **Step 5: Inspect working tree and commit final contract**

Run: `git status --short`

Expected: only files owned by this task plus pre-existing user changes are visible; no generated runtime artifacts are staged.

```bash
git add docs/architecture/analysis-context.md packages/grid-agent/tests/contract/test_analysis_context_docs.py packages/grid-agent/tests/e2e/test_continuous_analysis.py packages/grid-agent/tests/e2e/test_semantic_pi_path.py
git commit -m "test: verify continuous analysis context end to end"
```

## Final Verification Checklist

- [ ] `git log --oneline -12` shows one atomic commit per task and no temporary merge/worktree commits.
- [ ] `git status --short` contains no implementation leftovers; pre-existing user modifications remain intact.
- [ ] A replayed ledger equals the final checked snapshot and state hash.
- [ ] The E2E has exactly one Pi process marker and three ordered answer envelopes.
- [ ] The second and third turns use actual prior references in tool inputs.
- [ ] The report displays one global simulator baseline and per-turn context revision changes.
- [ ] Submitted answers match answer drafts, per-turn answer JSON, JSONL, and Markdown.
- [ ] Audit diagnostics do not replace answers; simulator artifact corruption prevents another turn.
- [ ] Standard traces contain no token/reasoning deltas or repeated message snapshots.
- [ ] `make doctor`, `make test`, `make test-e2e`, and `make validate` pass.
