# Trajectory Projections and v0.2 Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic Agent, Business, Context, and Artifact projections over native events and import the immutable `v0.2` golden run without inventing missing data.

**Architecture:** A small `ReplayEventLike` protocol lets pure projectors consume either verified native `RunEvent` values or explicitly labeled `ImportedRunEvent` values. Native events retain their authoritative hash chain; the importer builds a deterministic partial-order linearization and a separate normalization hash chain whose integrity label never claims original total order. Projection caches are disposable canonical JSON under `.grid-agent/trajectory-cache/`.

**Tech Stack:** Python 3.12+, Pydantic 2.12, standard-library JSON/hashlib/pathlib/heapq, existing Analysis reducers and content-reference verifier, pytest 9.

## Global Constraints

- Projectors are pure reducers over a validated event prefix and registered immutable artifacts.
- The same event prefix and artifacts produce byte-identical canonical projection output.
- Projection caches are never authority and may be deleted/rebuilt at any time.
- `observed` and `agent-declared` are persisted sources; `derived` exists only in projection nodes with explicit `rule_id` and `source_sequences`.
- No business projection may assert a numerical or network-specific fact without a verified simulator result/evidence source.
- Missing historical timestamps, request inputs, TTFT, usage, decisions, claims, or relations remain `unavailable`; no prose inference is allowed.
- `ImportedRunEvent.schema_version` is `grid-run-import-event/1.0`; it is never serialized as `grid-run-event/1.0`.
- Legacy normalization hashes detect cache corruption only and are labeled `importer-integrity`; original source file digests/coordinates remain attached.
- Context time travel returns before state, typed delta, after state, and the next exact request input when present.
- Historical `runs/analysis-20260814T081822Z` remains byte-for-byte unchanged.
- Use red/green TDD, focused tests first, and one atomic commit per task.

## File Map

### New production files

- `packages/grid-agent/src/grid_agent/trajectory/replay.py` — native/imported replay abstraction and validation boundary.
- `packages/grid-agent/src/grid_agent/trajectory/projection_models.py` — stable Agent/Business/Context/Artifact output models.
- `packages/grid-agent/src/grid_agent/trajectory/agent_projection.py` — turn/step/request/retry/tool lifecycle reducer.
- `packages/grid-agent/src/grid_agent/trajectory/business_projection.py` — business-first problem/decision/action/context/claim/evidence reducer.
- `packages/grid-agent/src/grid_agent/trajectory/context_projection.py` — event-level state frames, deltas, checkpoints, and request-input links.
- `packages/grid-agent/src/grid_agent/trajectory/artifact_projection.py` — bidirectional ref/producer/consumer index.
- `packages/grid-agent/src/grid_agent/trajectory/materialize.py` — canonical atomic cache materialization and rebuild.
- `packages/grid-agent/src/grid_agent/trajectory/legacy_v02.py` — deterministic `v0.2` importer.
- `packages/grid-agent/src/grid_agent/trajectory/service.py` — open native/legacy run and expose all four projections.
- `scripts/validate_trajectory_golden.py` — immutable golden-run acceptance command.

### Tests

- `packages/grid-agent/tests/trajectory/projections/test_agent.py`
- `packages/grid-agent/tests/trajectory/projections/test_business.py`
- `packages/grid-agent/tests/trajectory/projections/test_context.py`
- `packages/grid-agent/tests/trajectory/projections/test_artifacts.py`
- `packages/grid-agent/tests/trajectory/test_materialize.py`
- `packages/grid-agent/tests/trajectory/test_legacy_v02.py`
- `packages/grid-agent/tests/trajectory/test_service.py`
- `packages/grid-agent/tests/fixtures/trajectory/v02-golden-contract.json` — non-sensitive expected counts, source digests, and Q7 refs for the local golden run.

---

### Task 1: Common replay and projection models

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/replay.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/projection_models.py`
- Create: `packages/grid-agent/tests/trajectory/test_service.py`

**Interfaces:**
- Produces: `ImportedRunEvent`, `SourceCoordinate`, and runtime-checkable `ReplayEventLike` protocol.
- Produces output models `AgentTrajectory`, `BusinessTrajectory`, `ContextTimeline`, `ArtifactIndex`, `ProjectionDiagnostic`, and `ProjectedRun`.
- Every node has stable `id`, `source`, `source_sequences`, `status`, and optional `unavailable_reason`.

- [ ] **Step 1: Write failing replay/model tests**

```python
def test_imported_event_keeps_null_time_and_importer_integrity_label() -> None:
    event = ImportedRunEvent(
        analysis_id="analysis-old",
        sequence=1,
        timestamp=None,
        event_type="turn.started",
        import_previous_hash="sha256:" + "0" * 64,
        import_hash="sha256:" + "1" * 64,
        source_coordinate=SourceCoordinate(path="context/context-events.jsonl", sequence=2, sha256="a" * 64),
        scope=RunScope(turn_id="analysis-old-t001"),
        source=EventSource(kind="observed", producer="legacy-v0.2-importer", integrity="importer-integrity"),
        payload={"ordinal": 1, "instruction_sha256": "b" * 64},
    )
    assert event.schema_version == "grid-run-import-event/1.0"
    assert event.timestamp is None
    assert event.source.integrity == "importer-integrity"


def test_projection_nodes_require_provenance_for_derived_source() -> None:
    with pytest.raises(ValidationError, match="derived node requires"):
        BusinessNode(id="node-1", source="derived", source_sequences=(), rule_id=None, status="completed", kind="context-change", title="Changed")
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py -q`

Expected: FAIL because replay and projection models do not exist.

- [ ] **Step 3: Implement the explicit common protocol**

```python
@runtime_checkable
class ReplayEventLike(Protocol):
    analysis_id: str
    sequence: int
    timestamp: str | None
    event_type: str
    scope: RunScope
    causation: Causation
    source: EventSource
    context: ContextBoundary
    refs: EventRefs
    payload: dict[str, Any]


class ImportedRunEvent(StrictFrozenModel):
    schema_version: Literal["grid-run-import-event/1.0"] = "grid-run-import-event/1.0"
    analysis_id: str
    sequence: int = Field(ge=1)
    timestamp: str | None
    event_type: str
    import_previous_hash: str
    import_hash: str
    source_coordinate: SourceCoordinate
    scope: RunScope = Field(default_factory=RunScope)
    causation: Causation = Field(default_factory=Causation)
    source: EventSource
    context: ContextBoundary = Field(default_factory=ContextBoundary)
    refs: EventRefs = Field(default_factory=EventRefs)
    payload: dict[str, Any] = Field(default_factory=dict)
```

Define frozen output models with `extra="forbid"`. `BusinessNode` validates `source="derived"` requires non-empty `source_sequences` and `rule_id`; observed/agent-declared nodes require source sequences but no rule. `ContextFrame` requires ordered `before_revision <= after_revision`, explicit `delta`, state hashes, and nullable `request_artifact_ref` with `unavailable_reason`.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_service.py -q`

Expected: native/imported distinction and all output-model invariants pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/replay.py packages/grid-agent/src/grid_agent/trajectory/projection_models.py packages/grid-agent/tests/trajectory/test_service.py
git commit -m "feat: define trajectory replay projections"
```

### Task 2: Agent and Business projectors

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/agent_projection.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/business_projection.py`
- Create: `packages/grid-agent/tests/trajectory/projections/test_agent.py`
- Create: `packages/grid-agent/tests/trajectory/projections/test_business.py`

**Interfaces:**
- Produces: `project_agent(events: Sequence[ReplayEventLike]) -> AgentTrajectory`.
- Produces: `project_business(events, artifacts: ArtifactResolver) -> BusinessTrajectory`.
- Agent hierarchy: Analysis → Turn → Step → ModelRequest → Retry/AssistantResponse/ToolCall tree.
- Business node rules are named constants such as `RULE_TOOL_ACTION`, `RULE_CONTEXT_CHANGE`, and `RULE_VERIFIED_RESULT`.

- [ ] **Step 1: Write failing hierarchy/provenance tests**

```python
def test_agent_projection_pairs_tools_by_id_not_adjacency() -> None:
    events = interleaved_tool_fixture()
    trajectory = project_agent(events)
    request = trajectory.turns[0].steps[0].request
    assert [(tool.tool_call_id, tool.status) for tool in request.tools] == [
        ("call-a", "completed"), ("call-b", "failed")
    ]
    assert request.tools[0].start_sequence == 3
    assert request.tools[0].end_sequence == 6


def test_agent_projection_marks_open_tool_interrupted_only_after_closed_run() -> None:
    trajectory = project_agent(closed_run_with_open_tool())
    tool = trajectory.turns[0].steps[0].request.tools[0]
    assert tool.status == "interrupted"
    assert tool.duration_seconds is None


def test_business_projection_separates_declared_derived_and_observed() -> None:
    trajectory = project_business(q7_native_fixture(), verified_artifacts())
    assert [node.source for node in trajectory.problems[0].nodes] == [
        "agent-declared", "observed", "derived", "agent-declared", "observed"
    ]
    derived = next(node for node in trajectory.problems[0].nodes if node.source == "derived")
    assert derived.rule_id == "context-state-delta/v1"
    assert derived.source_sequences


def test_business_projection_refuses_unverified_numeric_result() -> None:
    with pytest.raises(ProjectionIntegrityError, match="verified simulator artifact"):
        project_business(q7_native_fixture(), artifacts_with_tampered_result())
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/projections/test_business.py -q`

Expected: FAIL because the projectors do not exist.

- [ ] **Step 3: Implement pure lifecycle and business reducers**

```python
def project_agent(events: Sequence[ReplayEventLike]) -> AgentTrajectory:
    state = MutableAgentProjection()
    for event in events:
        handler = AGENT_HANDLERS.get(event.event_type)
        if handler is not None:
            handler(state, event)
    state.close_at_boundary(events[-1] if events else None)
    return state.freeze()


AGENT_HANDLERS = {
    "turn.started": _start_turn,
    "turn.completed": _complete_turn,
    "turn.failed": _fail_turn,
    "step.started": _start_step,
    "step.completed": _complete_step,
    "model.request.started": _start_request,
    "model.response.completed": _complete_response,
    "model.response.failed": _fail_response,
    "model.retry.scheduled": _retry_scheduled,
    "model.retry.started": _retry_started,
    "model.retry.exhausted": _retry_exhausted,
    "tool.started": _start_tool,
    "tool.completed": _complete_tool,
    "tool.failed": _fail_tool,
}
```

```python
def _verified_result_node(event: ReplayEventLike, artifacts: ArtifactResolver) -> BusinessNode:
    documents = [artifacts.verify(reference) for reference in (*event.refs.produced, *event.refs.evidence)]
    if not any(document.authority == "gridctl" and document.integrity == "verified" for document in documents):
        raise ProjectionIntegrityError("numerical business node requires a verified simulator artifact")
    return BusinessNode(
        id=f"business:{event.analysis_id}:{event.sequence}:result",
        source="observed",
        source_sequences=(event.sequence,),
        status="completed",
        kind="verified-result",
        title=semantic_tool_title(event.payload["capability"]),
        refs=tuple(event.refs.produced),
    )
```

Implement handlers for decisions, tool actions, context changes, claims, answers, audit findings, limitations, and failures. Never use answer text to add a node. Semantic tool titles come from project-owned capability documents; unknown names render as identifiers without inventing domain meaning.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/projections/test_business.py -q`

Expected: tool pairing, retry nesting, interrupted lifecycle, source labels, rule provenance, missing declarations, and verified-numeric-source tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/agent_projection.py packages/grid-agent/src/grid_agent/trajectory/business_projection.py packages/grid-agent/tests/trajectory/projections/test_agent.py packages/grid-agent/tests/trajectory/projections/test_business.py
git commit -m "feat: project agent and business trajectories"
```

### Task 3: Context time travel, artifact index, and cache rebuild

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/context_projection.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/artifact_projection.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/materialize.py`
- Create: `packages/grid-agent/tests/trajectory/projections/test_context.py`
- Create: `packages/grid-agent/tests/trajectory/projections/test_artifacts.py`
- Create: `packages/grid-agent/tests/trajectory/test_materialize.py`

**Interfaces:**
- Produces: `project_context(events, artifacts, *, checkpoint_interval=100) -> ContextTimeline`.
- Produces: `ContextTimeline.at_sequence(sequence) -> ContextFrame` using nearest checkpoint plus deltas.
- Produces: `project_artifacts(events, registry) -> ArtifactIndex` with bidirectional producers/consumers.
- Produces: `ProjectionMaterializer(cache_root).write(projected_run, source_fingerprint) -> MaterializedPaths` and `.load_if_current(...)`.

- [ ] **Step 1: Write failing time-travel/index/cache tests**

```python
def test_context_frame_returns_before_delta_after_and_request_input() -> None:
    timeline = project_context(context_change_fixture(), verified_artifacts(), checkpoint_interval=2)
    frame = timeline.at_sequence(4)
    assert frame.before_revision == 2
    assert frame.after_revision == 3
    assert frame.delta["calculations"]["added"] == [POWERFLOW_RESULT_REF]
    assert frame.after_state["domain_state"]["calculations"][POWERFLOW_RESULT_REF]["status"] == "converged"
    assert frame.request_artifact_ref == REQUEST_INPUT_REF


def test_context_frame_labels_missing_legacy_request_unavailable() -> None:
    frame = project_context(legacy_context_fixture(), verified_artifacts()).at_sequence(8)
    assert frame.request_artifact_ref is None
    assert frame.unavailable_reason == "legacy source did not capture model request input"


def test_artifact_index_is_bidirectional() -> None:
    index = project_artifacts(q7_native_fixture(), verified_artifact_registry())
    record = index.records[Q7_EVIDENCE_REF]
    assert record.producing_sequence == Q7_TOOL_COMPLETED_SEQUENCE
    assert Q7_CLAIM_SEQUENCE in record.consuming_sequences


def test_materialized_cache_rebuild_is_byte_identical(tmp_path: Path) -> None:
    first = materialize_fixture(tmp_path)
    first_bytes = {path.name: path.read_bytes() for path in first.all_paths}
    shutil.rmtree(first.cache_root)
    second = materialize_fixture(tmp_path)
    assert {path.name: path.read_bytes() for path in second.all_paths} == first_bytes
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_context.py packages/grid-agent/tests/trajectory/projections/test_artifacts.py packages/grid-agent/tests/trajectory/test_materialize.py -q`

Expected: FAIL because context/artifact projectors and materializer do not exist.

- [ ] **Step 3: Implement checkpoints, deltas, and disposable caches**

```python
@dataclass(frozen=True, slots=True)
class ContextCheckpoint:
    source_sequence: int
    context_revision: int
    state_hash: str
    state: AnalysisContext


def project_context(events, artifacts, *, checkpoint_interval: int = 100) -> ContextTimeline:
    state = initial_replay_state(events)
    frames: list[ContextFrame] = []
    checkpoints: list[ContextCheckpoint] = []
    for event in events:
        before = state
        state, delta = apply_context_event(state, event, artifacts)
        frames.append(build_context_frame(event, before, delta, state, artifacts))
        if event.sequence % checkpoint_interval == 0 or event.event_type in {"turn.completed", "analysis.completed"}:
            checkpoints.append(ContextCheckpoint(event.sequence, state.revision, state.state_hash, state))
    return ContextTimeline(frames=tuple(frames), checkpoints=tuple(checkpoints))
```

`apply_context_event` reuses the existing pure analysis reducer for native context events and consumes importer-provided before/after snapshots for legacy records. `ArtifactIndexRecord` stores safe run-relative path, digest, verification status, producer, consumers, turn/step/request/tool/result/evidence/claim IDs. `ProjectionMaterializer` writes canonical files to `.grid-agent/trajectory-cache/{analysis_id}/{source_fingerprint}/{projection_schema}/` through temporary files and fsync; a mismatched fingerprint/version is a cache miss, not corruption of source.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/projections/test_context.py packages/grid-agent/tests/trajectory/projections/test_artifacts.py packages/grid-agent/tests/trajectory/test_materialize.py -q`

Expected: before/delta/after, checkpoint replay equivalence, request linkage, stale-calculation labels, bidirectional refs, and byte-identical rebuild tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/context_projection.py packages/grid-agent/src/grid_agent/trajectory/artifact_projection.py packages/grid-agent/src/grid_agent/trajectory/materialize.py packages/grid-agent/tests/trajectory/projections packages/grid-agent/tests/trajectory/test_materialize.py
git commit -m "feat: project context and artifact timelines"
```

### Task 4: Deterministic v0.2 importer

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/legacy_v02.py`
- Create: `packages/grid-agent/tests/trajectory/test_legacy_v02.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/service.py`
- Modify: `packages/grid-agent/tests/trajectory/test_service.py`

**Interfaces:**
- Produces: `LegacyV02Importer(run_root).import_run() -> ImportedReplay`.
- `ImportedReplay.events` is a deterministic tuple; `.source_fingerprint` covers every read source file; `.diagnostics` lists unavailable fields and ambiguous ties.
- Ordering: context ledger order, semantic trace order, proven `trace_sequence` edges, turn boundaries, then stable `(source_rank, source_sequence)` tie-break.
- Produces: `ProjectionService(cache_root).open_run(run_root) -> ProjectedRun`, selecting native reader when `events/run-events.jsonl` exists and v0.2 importer otherwise.

- [ ] **Step 1: Write failing importer tests with a synthetic legacy layout**

```python
def test_v02_import_is_deterministic_and_preserves_source_files(tmp_path: Path) -> None:
    run_root = write_legacy_v02_fixture(tmp_path)
    before = tree_digests(run_root)
    first = LegacyV02Importer(run_root).import_run()
    second = LegacyV02Importer(run_root).import_run()
    assert first == second
    assert tree_digests(run_root) == before
    assert all(event.schema_version == "grid-run-import-event/1.0" for event in first.events)


def test_v02_import_uses_trace_sequence_as_proven_cross_stream_edge(tmp_path: Path) -> None:
    imported = LegacyV02Importer(write_legacy_v02_fixture(tmp_path)).import_run()
    tool = next(event for event in imported.events if event.event_type == "tool.completed")
    context = next(event for event in imported.events if event.event_type == "context.projected" and event.source_coordinate.sequence == 3)
    assert tool.sequence < context.sequence
    assert context.causation.parent_sequence == tool.sequence


def test_v02_import_does_not_create_decisions_claims_or_request_inputs(tmp_path: Path) -> None:
    imported = LegacyV02Importer(write_legacy_v02_fixture(tmp_path)).import_run()
    assert not any(event.event_type in {"business.decision.declared", "business.claim.declared", "model.request.started"} for event in imported.events)
    assert "model request input unavailable" in {diagnostic.message for diagnostic in imported.diagnostics}
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_legacy_v02.py packages/grid-agent/tests/trajectory/test_service.py -q`

Expected: FAIL because importer and service do not exist.

- [ ] **Step 3: Implement source readers and stable topological merge**

```python
SOURCE_RANK = {"manifest": 0, "context": 1, "trace": 2, "pi": 3, "turn": 4, "artifact": 5}


def _stable_topological_order(records: Sequence[LegacyRecord], edges: Sequence[tuple[str, str]]) -> tuple[LegacyRecord, ...]:
    incoming, outgoing = build_graph(records, edges)
    ready = [record for record in records if not incoming[record.id]]
    heapq.heapify(ready)
    ordered: list[LegacyRecord] = []
    while ready:
        record = heapq.heappop(ready)
        ordered.append(record)
        for child in sorted(outgoing[record.id]):
            incoming[child].remove(record.id)
            if not incoming[child]:
                heapq.heappush(ready, record_by_id[child])
    if len(ordered) != len(records):
        raise LegacyImportError("legacy source constraints contain a cycle")
    return tuple(ordered)
```

`LegacyRecord.__lt__` compares `(SOURCE_RANK[source_kind], source_sequence, id)`. Parse and validate `manifest.json`, context JSONL with current `AnalysisContextEvent`, semantic trace JSONL, Pi session JSONL, turn answers/audits, tool-result/result/evidence artifacts, and report presence. Build one imported event per proven lifecycle record, retain source path/line/digest, set null timestamps when absent, and compute import hashes over normalized canonical records. Do not write beneath `run_root`; cache only through `ProjectionService`.

- [ ] **Step 4: Run focused tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/test_legacy_v02.py packages/grid-agent/tests/trajectory/test_service.py -q`

Expected: deterministic merge, byte preservation, trace edges, missing-data diagnostics, corrupt ledger/trace/artifact, cycle, and native-vs-legacy selection tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/legacy_v02.py packages/grid-agent/src/grid_agent/trajectory/service.py packages/grid-agent/tests/trajectory/test_legacy_v02.py packages/grid-agent/tests/trajectory/test_service.py
git commit -m "feat: import legacy v0.2 trajectories"
```

### Task 5: Golden-run validator and projection gate

**Files:**
- Create: `scripts/validate_trajectory_golden.py`
- Create: `packages/grid-agent/tests/fixtures/trajectory/v02-golden-contract.json`
- Modify: `Makefile`
- Modify: `docs/RUNBOOK.md`

**Interfaces:**
- CLI: `python scripts/validate_trajectory_golden.py RUN_ROOT` writes one JSON summary to stdout and diagnostics to stderr.
- Summary fields: `analysis_id`, `source_unchanged`, `turn_count`, `tool_start_count`, `tool_result_count`, `paired_tool_count`, `q7_lineage_verified`, and `projection_digests`.
- Make target: `make test-trajectory-golden GOLDEN_RUN=runs/analysis-20260814T081822Z`.

- [ ] **Step 1: Write the validator acceptance in code**

```python
def validate(run_root: Path) -> dict[str, object]:
    before = tree_digests(run_root)
    projected = ProjectionService(cache_root=run_root.parents[1] / ".grid-agent/trajectory-cache").open_run(run_root)
    after = tree_digests(run_root)
    q7 = projected.business.problem_by_turn(f"{run_root.name}-t007")
    paired = sum(len(step.request.tools) for turn in projected.agent.turns for step in turn.steps)
    return {
        "analysis_id": run_root.name,
        "source_unchanged": before == after,
        "turn_count": len(projected.agent.turns),
        "tool_start_count": projected.diagnostics.metrics["tool_start_count"],
        "tool_result_count": projected.diagnostics.metrics["tool_result_count"],
        "paired_tool_count": paired,
        "q7_lineage_verified": q7.has_verified_result_and_evidence_lineage(),
        "projection_digests": projected.canonical_digests(),
    }
```

The script exits 1 unless source is unchanged, turns equal 9, starts equal 36, results equal 36, paired tools equal 36, and Q7 lineage is true. It loads expected source/projection digests from `v02-golden-contract.json` and requires an explicit `--update-contract` flag to print proposed replacements; it never edits the contract or run automatically.

- [ ] **Step 2: Run against the actual golden run and observe the first mismatch**

Run: `uv run --project packages/grid-agent python scripts/validate_trajectory_golden.py runs/analysis-20260814T081822Z`

Expected: first run exits 1 only because `v02-golden-contract.json` has not yet been populated with measured digests; counts already report 9/36/36/36 and Q7 true.

- [ ] **Step 3: Record reviewed golden digests and rerun**

Run: `uv run --project packages/grid-agent python scripts/validate_trajectory_golden.py runs/analysis-20260814T081822Z --update-contract`

Expected: stdout is the complete deterministic digest/count document. Review it, then use `apply_patch` to replace `packages/grid-agent/tests/fixtures/trajectory/v02-golden-contract.json` with those exact values; the command itself must not edit the tracked contract or the golden run.

- [ ] **Step 4: Run golden and focused projection gates**

Run: `make test-trajectory-golden && uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q`

Expected: golden summary reports `source_unchanged=true`, 9 turns, 36 starts, 36 results, 36 pairs, and `q7_lineage_verified=true`; all projection tests pass.

- [ ] **Step 5: Document and commit**

```bash
git add scripts/validate_trajectory_golden.py packages/grid-agent/tests/fixtures/trajectory/v02-golden-contract.json Makefile docs/RUNBOOK.md
git commit -m "test: validate v0.2 trajectory replay"
```

### Task 6: Projection/import regression gate

**Files:**
- Verify only: Tasks 1–5 outputs.

**Interfaces:**
- Produces verification evidence only.

- [ ] **Step 1: Run all trajectory projection/import tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory -q`

Expected: all replay, projection, materialization, importer, and service tests pass with zero unexpected skips.

- [ ] **Step 2: Run the immutable golden gate twice**

Run: `make test-trajectory-golden && make test-trajectory-golden`

Expected: both runs produce identical projection digests and leave `git status --short runs/analysis-20260814T081822Z` empty.

- [ ] **Step 3: Run existing project gates serially**

Run: `make test && make test-e2e && make validate`

Expected: all existing tests and deterministic validations pass without provider credentials.

- [ ] **Step 4: Inspect the commit boundary**

Run: `git status --short && git log --oneline -6`

Expected: no uncommitted implementation changes; five task commits are visible. Do not create an empty verification commit.

## Self-Review

- Spec coverage: independent pure projections, stable agent hierarchy, business provenance/source kinds, numerical-source integrity, context time travel, checkpoints/deltas, artifact index, disposable caches, deterministic partial-order import, legacy missing-data semantics, source immutability, 9-turn/36-tool/Q7 golden acceptance are covered.
- Deferred intentionally: pagination/cursors, HTTP security, Web UI, and live streaming belong to later plans.
- Type consistency: `ProjectionService.open_run` produces the exact `ProjectedRun` consumed by the read-only API plan.
