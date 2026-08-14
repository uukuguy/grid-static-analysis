# Pandapower Capability Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `grid-agent analysis` carry a source-traceable pandapower domain state across ordered instructions, remove the legacy static policy, and expose current and future pandapower capability coverage without question-specific logic.

**Architecture:** Keep the existing append-only analysis ledger as the control-plane kernel. Extend simulator capability contracts with lifecycle/context metadata, project verified tool results into typed domain state, and inject a bounded human-readable view into the one Pi session. Full numerical artifacts remain under the run directory; the context and report contain typed summaries plus provenance.

**Tech Stack:** Python 3.12, Pydantic 2, pandapower 3.4.0, JSON Schema 2020-12, pytest 9, Pi RPC, `grid-capability` protocol 1.0.

## Global Constraints

- `grid-agent` stdout remains exactly one JSON object containing `question_id` and `answer_output`; diagnostics remain on stderr.
- Every numerical or network-specific claim crosses `gridctl` through `grid-capability` protocol 1.0.
- Pandapower remains pinned to exactly 3.4.0.
- Pi receives only project grid tools, `grid_guide_open`, and `grid_submit_answer`; do not expose shell, filesystem, Python, pandas, or raw `pandapowerNet` access.
- `analysis` remains one Pi process and one ordered conversation per command; do not add cross-run resume, named sessions, switching sessions, or concurrent turns.
- Full result tables stay in artifacts; bounded views retain source, model revision, scenario, solver status, and result applicability.
- Audit and context projection remain advisory and may not overwrite an already submitted answer.
- Known questions are acceptance examples only; runtime code may not branch on question text, question IDs, or expected answers.
- Do not modify or remove user-owned `var/`, `runs/`, `report-20260814/`, `validation/questions/task.md.txt`, or unrelated dirty status files.
- Use TDD for every behavior change: focused failing test, minimal implementation, focused pass, then commit.
- Known baseline: `packages/grid-simulator/tests/test_capability_contracts.py::test_packaged_contracts_cover_all_wp_a_capabilities` currently fails because the late policy capability was added without updating the expected catalog. Task 1 removes that legacy capability and restores the contract.

---

## File Structure

### Simulator contracts and execution

- Create `packages/grid-simulator/src/grid_simulator/constraints.py` — extract model-owned bounds and evaluate result rows against those bounds.
- Create `packages/grid-simulator/src/grid_simulator/capabilities/families.py` — versioned pandapower capability-family availability catalog.
- Create `packages/grid-simulator/src/grid_simulator/capabilities/definitions/model.constraints.describe.json` — semantic model-constraint query.
- Modify `packages/grid-simulator/src/grid_simulator/capabilities/schema.py` — capability availability and context-effect schema.
- Modify every JSON contract in `packages/grid-simulator/src/grid_simulator/capabilities/definitions/` — declare availability, state requirements, state products, result kind, and projector.
- Modify `packages/grid-simulator/src/grid_simulator/operations.py` — publish family status, dispatch model constraints, and remove policy dispatch.
- Modify `packages/grid-simulator/src/grid_simulator/analyses.py` — remove static limits and evaluate N-1 against model-owned constraints.
- Delete `packages/grid-simulator/src/grid_simulator/capabilities/definitions/analysis.policy.describe.json`.
- Delete `configs/policies/static-analysis-v1.json`.

### Agent context and projection

- Create `packages/grid-agent/src/grid_agent/analysis/capabilities.py` — validated capability context catalog loaded from simulator contracts.
- Create `packages/grid-agent/src/grid_agent/analysis/domain_projection.py` — projector registry selected by contract metadata.
- Modify `packages/grid-agent/src/grid_agent/analysis/models.py` — typed `DomainState` records and domain projection event.
- Modify `packages/grid-agent/src/grid_agent/analysis/reducer.py` — deterministic domain-state upserts and active-state invariants.
- Modify `packages/grid-agent/src/grid_agent/analysis/projector.py` — append domain projection events after verified tool results.
- Modify `packages/grid-agent/src/grid_agent/analysis/view.py` — bounded active model, capabilities, constraints, scenarios, and reusable calculations.
- Modify `packages/grid-agent/src/grid_agent/analysis/runner.py` — explicit continuous-reference instructions and concrete diagnostics.
- Modify `packages/grid-agent/src/grid_agent/analysis/report.py` — reader-first per-turn domain-state changes with artifact links.
- Modify `packages/grid-agent/src/grid_agent/cli/app.py` — wire capability metadata and family status into the store/projector.
- Modify `packages/grid-agent/src/grid_agent/tools/catalog.py` — validate context metadata while exposing only published executable tools.

### Knowledge, validation, schemas, and documentation

- Modify `packages/grid-agent/src/grid_agent/knowledge/offline.py` — remove the voltage-policy answer and policy arguments.
- Modify `configs/agent/system-policy.md` and `configs/runtime/grid-agent-system-policy.md` — require active-context resolution and sourced constraints.
- Modify `skills/grid-static-analysis/SKILL.md` and its capability/contingency references — remove static policy semantics and document model constraints.
- Delete `validation/suites/task-required/knowledge-voltage-range-001.json`.
- Modify affected N-1 validation cases to omit policy and expect sourced evaluation.
- Modify `schemas/analysis-context-v1.schema.json` and `schemas/analysis-context-event-v1.schema.json` through `scripts/update_analysis_context_schemas.py`.
- Modify `docs/architecture/analysis-context.md` — normative domain-state and capability-lifecycle contract.

---

### Task 1: Replace legacy policy with model-owned constraints

**Files:**
- Create: `packages/grid-simulator/src/grid_simulator/constraints.py`
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/definitions/model.constraints.describe.json`
- Modify: `packages/grid-simulator/src/grid_simulator/operations.py`
- Modify: `packages/grid-simulator/src/grid_simulator/analyses.py`
- Modify: `packages/grid-simulator/src/grid_simulator/capabilities/definitions/analysis.contingency.n_minus_one.run.json`
- Delete: `packages/grid-simulator/src/grid_simulator/capabilities/definitions/analysis.policy.describe.json`
- Delete: `configs/policies/static-analysis-v1.json`
- Create: `packages/grid-simulator/tests/test_constraints.py`
- Modify: `packages/grid-simulator/tests/test_contingency.py`
- Modify: `packages/grid-simulator/tests/test_capability_contracts.py`
- Modify: `packages/grid-simulator/tests/test_protocol.py`

**Interfaces:**
- Produces: `describe_model_constraints(net: Any, revision_ref: str) -> dict[str, Any]`.
- Produces: `evaluate_constraints(powerflow: Mapping[str, Any], constraints: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]`.
- Produces capability: `model.constraints.describe({context_ref})`.
- Changes capability: `analysis.contingency.n_minus_one.run({context_ref, branch_refs, ...solver options})`; `policy` is no longer accepted or returned.

- [ ] **Step 1: Write failing model-constraint tests**

Add exact assertions to `packages/grid-simulator/tests/test_constraints.py`:

```python
from __future__ import annotations


def test_ieee39_bus_voltage_constraints_come_from_model(grid, context_ref: str) -> None:
    result = grid.call("model.constraints.describe", {"context_ref": context_ref})

    voltage = next(item for item in result["constraints"] if item["quantity"] == "bus.vm_pu")
    assert voltage["lower"] == 0.94
    assert voltage["upper"] == 1.06
    assert voltage["unit"] == "p.u."
    assert voltage["applies_to_count"] == 39
    assert voltage["source"] == {
        "kind": "model",
        "table": "bus",
        "fields": ["min_vm_pu", "max_vm_pu"],
    }
    assert result["context_ref"] == context_ref
    assert result["revision_ref"].startswith("revision:sha256:")
    assert result["evidence_refs"]


def test_model_constraints_do_not_publish_project_policy(grid, context_ref: str) -> None:
    result = grid.call("model.constraints.describe", {"context_ref": context_ref})

    assert "policy" not in result
    assert all(item["source"]["kind"] == "model" for item in result["constraints"])
```

Update `test_contingency.py` calls to omit `policy`, assert it is absent from output, and assert each threshold-based violation has `constraint_ref` and `constraint_source == "model"`. Keep the existing golden loading assertions.

- [ ] **Step 2: Run the focused tests and confirm contract failures**

Run:

```bash
uv run --project packages/grid-simulator pytest \
  packages/grid-simulator/tests/test_constraints.py \
  packages/grid-simulator/tests/test_contingency.py \
  packages/grid-simulator/tests/test_capability_contracts.py -q
```

Expected: FAIL because `model.constraints.describe` is unknown, N-1 still requires `policy`, and the legacy policy contract is still packaged.

- [ ] **Step 3: Implement model constraint extraction**

In `constraints.py`, implement grouped, model-sourced constraints. Use pandapower table values, not constants:

```python
def describe_model_constraints(net: Any, revision_ref: str) -> dict[str, Any]:
    constraints = [
        *_bounded_groups(net.bus, revision_ref, "bus", "bus.vm_pu", "min_vm_pu", "max_vm_pu", "p.u."),
        *_upper_groups(net.line, revision_ref, "line", "branch.loading_percent", "max_loading_percent", "percent"),
        *_upper_groups(net.trafo, revision_ref, "trafo", "branch.loading_percent", "max_loading_percent", "percent"),
    ]
    return {"constraints": sorted(constraints, key=lambda item: item["constraint_ref"])}
```

Each grouped record must contain:

```python
{
    "constraint_ref": "constraint:sha256:<canonical model/revision/scope/value digest>",
    "quantity": "bus.vm_pu",
    "subject_kind": "bus",
    "lower": 0.94,
    "upper": 1.06,
    "unit": "p.u.",
    "applies_to_count": 39,
    "source": {"kind": "model", "table": "bus", "fields": ["min_vm_pu", "max_vm_pu"]},
}
```

Omit absent/NaN bounds rather than inventing defaults. Group only identical bound tuples; heterogeneous bounds remain separate records.

- [ ] **Step 4: Publish `model.constraints.describe` and remove policy dispatch**

Add `model.constraints.describe` to `EXECUTABLE_CAPABILITIES`, dispatch it after `context.get`, and return:

```python
def _model_constraints_describe(workspace, engine, arguments):
    context, net = _load_context_and_network(workspace, engine, str(arguments["context_ref"]))
    return {
        "context_ref": context.context_ref,
        "revision_ref": context.revision_ref,
        **describe_model_constraints(net, context.revision_ref),
    }
```

The new JSON contract accepts only `context_ref`; it produces `model.constraint` and `evidence.network_fact`, with `evidence_required: true`. Persist one content-addressed network-fact evidence document containing the revision, normalized constraints, pandapower provenance, and capability ID; return its reference in `evidence_refs`. Delete `_analysis_policy_describe`, the policy import, the policy capability JSON, and the policy config.

- [ ] **Step 5: Make N-1 constraint-aware without a policy argument**

Remove `STATIC_ANALYSIS_V1_LIMITS`. Resolve model constraints once from the base network and pass them to each scenario. Replace constant comparisons with per-subject model bounds. Preserve raw `max_loading_percent`, add `min_vm_pu` and `max_vm_pu`, and return:

```python
"constraint_evaluation": {
    "status": "evaluated" | "partially_evaluated" | "not_defined",
    "source": "model",
    "evaluated_quantities": [...],
    "unevaluated_quantities": [...],
}
```

Every low/high/overload record must identify the exact `constraint_ref`. Keep non-convergence as a calculation issue; do not manufacture a voltage/loading violation when the model has no corresponding bound.

- [ ] **Step 6: Update schemas and protocol tests**

Remove `policy` from N-1 required/properties/output. Add `constraint_evaluation`, `min_vm_pu`, `max_vm_pu`, and `constraint_ref` schemas. Update `EXPECTED_IDS` so it includes `model.constraints.describe` and excludes `analysis.policy.describe`. Assert a request containing legacy `policy` fails JSON-schema validation.

- [ ] **Step 7: Run simulator tests**

Run:

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -q
```

Expected: PASS, including IEEE-39 model values 0.94–1.06 p.u.; no published policy capability remains.

- [ ] **Step 8: Commit**

```bash
git add configs/policies packages/grid-simulator/src/grid_simulator packages/grid-simulator/tests
git commit -m "feat: derive analysis constraints from grid models"
```

---

### Task 2: Add capability lifecycle and context-effect metadata

**Files:**
- Create: `packages/grid-simulator/src/grid_simulator/capabilities/families.py`
- Modify: `packages/grid-simulator/src/grid_simulator/capabilities/schema.py`
- Modify: `packages/grid-simulator/src/grid_simulator/capabilities/registry.py`
- Modify: all `packages/grid-simulator/src/grid_simulator/capabilities/definitions/*.json`
- Modify: `packages/grid-simulator/src/grid_simulator/operations.py`
- Modify: `packages/grid-simulator/tests/test_capability_contracts.py`
- Modify: `packages/grid-simulator/tests/test_environment.py`
- Modify: `packages/grid-agent/src/grid_agent/tools/catalog.py`
- Modify: `packages/grid-agent/tests/tools/test_catalog.py`

**Interfaces:**
- Produces model: `CapabilityContextEffect` with `requires_state`, `consumes_state`, `produces_state`, `invalidates_state`, `result_kind`, and `projector`.
- Produces model: `CapabilityFamilyStatus(id, availability, reason)`.
- Extends `environment.describe` with `capability_families` and per-capability `availability`/`context_effect`.

- [ ] **Step 1: Write failing contract metadata tests**

Add:

```python
def test_every_contract_declares_context_effect() -> None:
    for contract in CapabilityRegistry.load_packaged().list():
        assert contract.availability == "published"
        assert contract.context_effect.projector
        assert contract.context_effect.produces_state or contract.context_effect.consumes_state


def test_environment_distinguishes_future_capability_families(grid) -> None:
    result = grid.call("environment.describe", {})
    families = {item["id"]: item["availability"] for item in result["capability_families"]}
    assert families["power-flow"] == "published"
    assert families["contingency"] == "published"
    assert families["opf"] == "not_published"
    assert families["short-circuit"] == "not_published"
    assert families["state-estimation"] == "not_published"
    assert families["time-series"] == "not_published"
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run --project packages/grid-simulator pytest \
  packages/grid-simulator/tests/test_capability_contracts.py \
  packages/grid-simulator/tests/test_environment.py -q
```

Expected: FAIL because the schema and environment response lack lifecycle metadata.

- [ ] **Step 3: Extend the strict contract schema**

Add:

```python
CapabilityAvailability = Literal["published", "not_published", "not_applicable", "unavailable", "failed"]


class CapabilityContextEffect(StrictModel):
    requires_state: tuple[str, ...]
    consumes_state: tuple[str, ...]
    produces_state: tuple[str, ...]
    invalidates_state: tuple[str, ...] = ()
    result_kind: str | None = None
    projector: str
```

Make `availability: CapabilityAvailability` and `context_effect: CapabilityContextEffect` required on `CapabilityContract`.

- [ ] **Step 4: Add exact metadata to every published contract**

Use these projector IDs and state products:

| Capability | Projector | Produces state |
|---|---|---|
| `environment.describe` | `capability-catalog-v1` | `capabilities.catalog` |
| `model.list` | `model-catalog-v1` | `model.catalog` |
| `context.open`, `context.get` | `model-context-v1` | `model.active` |
| `model.constraints.describe` | `model-constraints-v1` | `constraints.model` |
| `model.element.get`, dataset describe/query | `model-observation-v1` | `model.observation` |
| topology capabilities | `topology-observation-v1` | `topology.observation` |
| `analysis.powerflow.ac.run` | `powerflow-ac-v1` | `calculations.powerflow` |
| `result.branches.rank` | `result-view-v1` | `calculations.result_view` |
| `analysis.contingency.n_minus_one.run` | `contingency-n1-v1` | `scenarios.contingency`, `calculations.contingency` |
| `evidence.get` | `artifact-observation-v1` | `artifacts.observation` |

All current executable contracts declare `availability: "published"`. Their `requires_state` must name semantic state such as `model.active`, not another tool name.

- [ ] **Step 5: Add the family catalog**

Define immutable records for published families `model-context`, `model-data`, `topology`, `power-flow`, `result-analysis`, `contingency`, and `evidence`; define `opf`, `short-circuit`, `state-estimation`, `time-series`, and `model-lifecycle` as `not_published` with a concise reason. Do not create tools for unpublished families.

- [ ] **Step 6: Extend `environment.describe` and tool catalog validation**

Return each executable capability's lifecycle metadata plus `capability_families`. `ToolCatalog.from_environment` continues to expose only IDs listed in `executable_capabilities`; validate that each selected document is `published` and its context metadata matches the environment response.

- [ ] **Step 7: Run focused and package tests**

Run:

```bash
uv run --project packages/grid-simulator pytest packages/grid-simulator/tests -q
uv run --project packages/grid-agent pytest packages/grid-agent/tests/tools -q
```

Expected: PASS; future families appear as unavailable-by-design metadata and never as model tools.

- [ ] **Step 8: Commit**

```bash
git add packages/grid-simulator/src/grid_simulator/capabilities \
  packages/grid-simulator/src/grid_simulator/operations.py \
  packages/grid-simulator/tests \
  packages/grid-agent/src/grid_agent/tools/catalog.py \
  packages/grid-agent/tests/tools
git commit -m "feat: publish pandapower capability lifecycle metadata"
```

---

### Task 3: Add typed pandapower domain state to AnalysisContext

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/models.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/reducer.py`
- Modify: `packages/grid-agent/tests/analysis/test_reducer.py`
- Modify: `packages/grid-agent/tests/analysis/test_store.py`
- Modify: `scripts/update_analysis_context_schemas.py`
- Modify generated: `schemas/analysis-context-v1.schema.json`
- Modify generated: `schemas/analysis-context-event-v1.schema.json`

**Interfaces:**
- Produces: `DomainState`, `ActiveModelState`, `CapabilityState`, `ConstraintState`, `ScenarioState`, `CalculationState`, `ArtifactState`.
- Produces event: `domain.state.projected` with a strict `DomainStateDelta` payload.
- Preserves: `analysis-context/1.0` as a compatible optional-field extension; old ledgers materialize empty `domain_state` through defaults.

- [ ] **Step 1: Write failing reducer tests**

Add a test that opens a baseline, projects model state, then projects a power-flow calculation:

```python
def test_domain_projection_tracks_model_and_result_applicability(context_store) -> None:
    # use the existing turn/baseline helpers
    context_store.append(ContextEventDraft(
        event_type="domain.state.projected",
        turn_id="analysis-test-t001",
        capability="context.open",
        payload={
            "projector": "model-context-v1",
            "model": {
                "context_ref": CONTEXT_REF,
                "revision_ref": REVISION_REF,
                "model_id": "ieee39",
                "source": "pandapower.networks.case39",
                "counts": {"buses": 39, "lines": 35, "transformers": 11},
            },
        },
    ))
    assert context_store.snapshot.domain_state.model.model_id == "ieee39"
```

Add tests rejecting a calculation whose `revision_ref` differs from the active model, and preserving an old calculation after a new active model is projected.

- [ ] **Step 2: Run reducer tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_reducer.py \
  packages/grid-agent/tests/analysis/test_store.py -q
```

Expected: FAIL because the event and typed state do not exist.

- [ ] **Step 3: Define strict domain models**

Use Pydantic frozen models. Required shapes:

```python
class ActiveModelState(StrictFrozenModel):
    context_ref: str
    revision_ref: str
    model_id: str
    source: str
    counts: dict[str, int] = Field(default_factory=dict)


class ConstraintState(StrictFrozenModel):
    constraint_ref: str
    context_ref: str
    revision_ref: str
    quantity: str
    subject_kind: str
    lower: float | None = None
    upper: float | None = None
    unit: str
    applies_to_count: int
    source_kind: Literal["model", "user", "standard", "task"]
    source_ref: str
    producer_capability: str
    producer_turn_id: str


class CalculationState(StrictFrozenModel):
    result_ref: str
    kind: str
    context_ref: str
    revision_ref: str
    scenario_refs: list[str] = Field(default_factory=list)
    status: str
    solver: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str
    evidence_refs: list[str] = Field(default_factory=list)
    producer_capability: str
    producer_turn_id: str
```

Define equally strict `CapabilityState`, `ScenarioState`, and `ArtifactState`. `DomainState` contains `model`, `operating_state`, and dicts keyed by stable refs for constraints, scenarios, calculations, capabilities, and artifacts.

- [ ] **Step 4: Add and reduce `domain.state.projected`**

Add the event to `EventType`. Validate payload through `DomainStateDelta`; upsert records idempotently; reject conflicting duplicates; ensure calculation/constraint/scenario revisions resolve to known baselines. A newly active model changes only `domain_state.model`; historical calculations stay registered and are marked non-active by view logic rather than deleted.

- [ ] **Step 5: Seed capability family state from runtime**

Extend `RuntimeRecord` with `capability_families: list[CapabilityState] = Field(default_factory=list)`. `initial_context` copies these records into `domain_state.capabilities`. Existing fixtures that omit the field continue to work.

- [ ] **Step 6: Regenerate schemas and verify replay**

Run:

```bash
uv run --project packages/grid-agent python scripts/update_analysis_context_schemas.py
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_reducer.py \
  packages/grid-agent/tests/analysis/test_store.py \
  packages/grid-agent/tests/contract/test_analysis_context_docs.py -q
```

Expected: PASS; replay produces the same domain state and canonical state hash.

- [ ] **Step 7: Commit**

```bash
git add packages/grid-agent/src/grid_agent/analysis/models.py \
  packages/grid-agent/src/grid_agent/analysis/reducer.py \
  packages/grid-agent/tests/analysis/test_reducer.py \
  packages/grid-agent/tests/analysis/test_store.py \
  schemas scripts/update_analysis_context_schemas.py
git commit -m "feat: add typed pandapower analysis domain state"
```

---

### Task 4: Project verified capability results through contract-selected projectors

**Files:**
- Create: `packages/grid-agent/src/grid_agent/analysis/capabilities.py`
- Create: `packages/grid-agent/src/grid_agent/analysis/domain_projection.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/projector.py`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/analysis/test_projector.py`
- Create: `packages/grid-agent/tests/analysis/test_capabilities.py`
- Create: `packages/grid-agent/tests/analysis/test_domain_projection.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py`

**Interfaces:**
- Produces: `CapabilityContextCatalog.from_documents(documents) -> CapabilityContextCatalog`.
- Produces: `CapabilityContextCatalog.require(capability_id) -> CapabilityContextSpec`.
- Produces: `project_domain_result(spec, result, args, artifacts, turn_id) -> DomainStateDelta | None`.
- Changes: `AnalysisContextProjector(store, verifier, capability_catalog)`.

- [ ] **Step 1: Write failing capability-catalog and projector tests**

Assert unknown projector IDs fail at startup, not mid-analysis:

```python
def test_context_catalog_rejects_unknown_projector(capability_documents) -> None:
    document = {**capability_documents[0], "context_effect": {
        **capability_documents[0]["context_effect"], "projector": "missing-v1"
    }}
    with pytest.raises(CapabilityContextError, match="unknown context projector"):
        CapabilityContextCatalog.from_documents((document,))
```

Extend projector tests to assert:

- `context.open` sets the active model;
- `model.constraints.describe` registers 0.94/1.06 model constraints with source refs;
- AC power flow registers a reusable calculation tied to the active revision;
- branch ranking consumes that calculation without creating a duplicate result;
- N-1 registers scenario/calculation state and retains raw metrics;
- a projection failure records advisory diagnostics but does not reject answer submission.

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_capabilities.py \
  packages/grid-agent/tests/analysis/test_domain_projection.py \
  packages/grid-agent/tests/analysis/test_projector.py -q
```

Expected: FAIL because metadata is not loaded and no domain projection event is emitted.

- [ ] **Step 3: Implement the context catalog**

Parse only the required contract fields into:

```python
@dataclass(frozen=True, slots=True)
class CapabilityContextSpec:
    capability: str
    availability: str
    requires_state: tuple[str, ...]
    consumes_state: tuple[str, ...]
    produces_state: tuple[str, ...]
    invalidates_state: tuple[str, ...]
    result_kind: str | None
    projector: str
```

Maintain an explicit allowlist of implemented projector IDs matching Task 2. Reject `not_published` contracts from the executable projection catalog.

- [ ] **Step 4: Implement small projector functions**

`domain_projection.py` contains one focused function per projector ID. It receives verified result mappings and verified artifact paths; it does not open artifacts independently or perform electrical calculations. For example, `powerflow-ac-v1` emits one `CalculationState` using `result_ref`, `context_ref`, `revision_ref`, solver/convergence/loss summary, artifact path, evidence refs, capability, and turn.

`model-constraints-v1` converts each returned constraint to a `ConstraintState` and uses the verified constraint evidence reference as `source_ref`; the table/field origin remains in the constraint summary.

- [ ] **Step 5: Append domain projection after verified registration**

After observation/result/evidence admission succeeds, obtain the contract-selected projector and append one `domain.state.projected` event. The event must reference the same turn and capability. If projection fails, preserve the current advisory behavior: trace `analysis_context.projection_failed`, record a readable diagnostic if possible, and allow Pi to continue.

- [ ] **Step 6: Wire the same semantic documents at CLI startup**

Load capability documents once in `_execute_analysis`, pass them both to `ToolCatalog.from_environment` and `CapabilityContextCatalog.from_documents`, and seed `_runtime_record` from `environment_description["capability_families"]`. Do not make `grid-agent` import `grid_simulator` Python modules.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis \
  packages/grid-agent/tests/cli/test_app.py -q
```

Expected: PASS.

```bash
git add packages/grid-agent/src/grid_agent/analysis \
  packages/grid-agent/src/grid_agent/cli/app.py \
  packages/grid-agent/tests/analysis \
  packages/grid-agent/tests/cli/test_app.py
git commit -m "feat: project capability results into analysis state"
```

---

### Task 5: Expose a bounded continuous context and reader-first report

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/analysis/view.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/runner.py`
- Modify: `packages/grid-agent/src/grid_agent/analysis/report.py`
- Modify: `packages/grid-agent/tests/analysis/test_view.py`
- Modify: `packages/grid-agent/tests/analysis/test_runner.py`
- Modify: `packages/grid-agent/tests/analysis/test_report.py`

**Interfaces:**
- `build_context_view` adds `active_model`, `capability_status`, `constraints`, `reusable_calculations`, and `scenarios`.
- Report context renders model/constraints/calculations by semantic labels and links IDs only in detailed artifacts.

- [ ] **Step 1: Write failing view tests**

Build a context with an active IEEE-39 model, a model constraint, an active power-flow result, a stale result from another revision, and future capability families. Assert:

```python
assert view["active_model"]["model_id"] == "ieee39"
assert view["constraints"][0]["quantity"] == "bus.vm_pu"
assert view["constraints"][0]["source_kind"] == "model"
assert [item["result_ref"] for item in view["reusable_calculations"]] == [ACTIVE_RESULT_REF]
assert any(item["id"] == "opf" and item["availability"] == "not_published" for item in view["capability_status"])
assert STALE_RESULT_REF not in json.dumps(view)
```

Keep the 64 KiB bound test and prove that omitted arrays remain reachable through `artifact_path`.

- [ ] **Step 2: Write failing runner/report tests**

Assert the second prompt includes the active model and model constraints without relying on the first assistant message. Assert the report displays:

- `IEEE-39（pandapower.networks.case39）`;
- `母线电压约束：0.94–1.06 p.u.（模型数据）`;
- calculation/scenario status in Chinese;
- no raw `context:sha256`, `revision:sha256`, or `result:sha256` in the main narrative;
- detailed trace and context artifact links remain present.

- [ ] **Step 3: Run focused tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/analysis/test_view.py \
  packages/grid-agent/tests/analysis/test_runner.py \
  packages/grid-agent/tests/analysis/test_report.py -q
```

Expected: FAIL because the current view is provenance-only and the report does not render domain-state changes.

- [ ] **Step 4: Build the active, bounded view**

Select reusable calculations only when `context_ref` and `revision_ref` match the active model. Include scenario and constraint summaries with semantic values and source. Keep historical records in `analysis-context.json`, but omit inactive results from the injected view. Preserve existing `completed_turns`, `verified_facts`, and concrete diagnostics.

- [ ] **Step 5: Strengthen continuous-reference instructions**

Update `_prompt_for` with these rules:

```text
后续指令省略模型、场景或结果时，先使用 analysis_context_view 中的活动对象。
网络与数值结论只能来自已发布 grid tools 或其中登记的可复用结果。
判断正常、越限或风险时必须指出约束来源；没有约束时只报告原始值，不得猜测阈值。
not_published、not_applicable、prerequisite_missing 和计算失败必须分别说明，不得统称执行限制。
```

Do not add examples containing the current validation questions or expected answers.

- [ ] **Step 6: Render per-turn domain state without burying answers**

Keep the current section order: question, answer, execution information, simulation context, actual process, evidence. In “仿真环境上下文”, show only the active model and domain-state records consumed/produced by that turn. Use short labels in the report and keep long IDs in `context/analysis-context.json` and turn trace pages.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/analysis -q
```

Expected: PASS.

```bash
git add packages/grid-agent/src/grid_agent/analysis \
  packages/grid-agent/tests/analysis
git commit -m "feat: expose continuous pandapower state in analysis reports"
```

---

### Task 6: Remove policy knowledge shortcuts and align skills/validation

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/knowledge/offline.py`
- Modify: `packages/grid-agent/tests/knowledge/test_offline.py`
- Modify: `packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py`
- Modify: `configs/agent/system-policy.md`
- Modify: `configs/runtime/grid-agent-system-policy.md`
- Modify: `skills/grid-static-analysis/SKILL.md`
- Modify: `skills/grid-static-analysis/references/capability-map.md`
- Modify: `skills/grid-static-analysis/references/contingency-analysis.md`
- Modify: `skills/grid-static-analysis/references/future-capabilities.md`
- Delete: `validation/suites/task-required/knowledge-voltage-range-001.json`
- Modify: `validation/suites/task-required/analysis-critical-line-outage-ordering-001.json`
- Modify: `validation/suites/static-analysis-core/static-n1-partial-failure-001.json`
- Modify: `packages/grid-agent/tests/validation/test_case_contract.py`
- Modify: `packages/grid-agent/tests/validation/test_run_harness.py`

**Interfaces:**
- `answer_information("母线电压正常运行范围是多少") -> None` because the question requires active model context or an explicit standard.
- Offline N-1 calls omit `policy`.
- Validation no longer treats voltage range as a zero-tool knowledge fact.

- [ ] **Step 1: Write failing offline and validation tests**

Change the knowledge test to:

```python
assert offline.answer_information("母线电压正常运行范围是多少?") is None
```

Assert offline N-1 client calls contain no `policy`. Remove `knowledge-voltage-range-001` from expected case IDs and add a contract assertion that no validation case requires `static-analysis-v1`.

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/knowledge \
  packages/grid-agent/tests/validation/test_case_contract.py \
  packages/grid-agent/tests/validation/test_run_harness.py -q
```

Expected: FAIL while the offline entry and policy-bearing fixtures remain.

- [ ] **Step 3: Remove the knowledge shortcut and policy arguments**

Delete the voltage-range `KnowledgeEntry` and its keyword branch. Retain informational entries only when their source is a reviewed capability guide and they do not claim model-specific values. Update diagnostic N-1 invocations to `{context_ref, branch_refs}`.

- [ ] **Step 4: Rewrite operator and Skill guidance**

State that voltage/loading limits are model constraints, user criteria, or explicitly named standards. Document `model.constraints.describe`, raw N-1 metrics, and `constraint_evaluation`. Remove all `static-analysis-v1`, 0.95/1.05, and “published policy” language. Keep the distinction between network calculations and offline conceptual explanations.

- [ ] **Step 5: Replace validation assumptions**

Delete the zero-tool voltage case. Remove `policy` arguments from N-1 cases. Require constraint source fields where a validation case asserts a violation. Do not hard-code 0.94/1.06 into generic knowledge validation; those values belong only to simulator-backed IEEE-39 fixtures.

- [ ] **Step 6: Search for stale product-policy semantics**

Run:

```bash
rg -n "static-analysis-v1|analysis\.policy\.describe|0\.95|1\.05" \
  configs packages skills validation \
  -g '!configs/llm-providers.json'
```

Expected: no matches. Provider configuration fields named `base_url_policy` are unrelated and remain unchanged.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/knowledge \
  packages/grid-agent/tests/validation \
  packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py -q
```

Expected: PASS.

```bash
git add configs/agent configs/runtime \
  packages/grid-agent/src/grid_agent/knowledge \
  packages/grid-agent/tests/knowledge \
  packages/grid-agent/tests/validation \
  packages/grid-agent/tests/e2e/test_offline_walking_skeleton.py \
  skills/grid-static-analysis validation/suites
git commit -m "refactor: remove legacy policy answer shortcuts"
```

---

### Task 7: Prove continuous context generalizes beyond the known question list

**Files:**
- Modify: `packages/grid-agent/tests/e2e/test_continuous_analysis.py`
- Modify: `packages/grid-agent/tests/e2e/test_semantic_pi_path.py`
- Modify: `packages/grid-agent/tests/contract/test_analysis_context_docs.py`
- Modify: `docs/architecture/analysis-context.md`
- Modify generated schemas if model documentation changes: `schemas/analysis-context-*.schema.json`

**Interfaces:**
- End-to-end flow: open model → inherit active model → describe model constraints → run/reuse power flow → rank → run N-1.
- Held-out wording proves semantic state resolution without runtime question branches.

- [ ] **Step 1: Extend the scripted continuous E2E test**

Use ordered instructions with wording different from `validation/questions/task.md.txt`:

```python
prompts = (
    "载入 IEEE-39 并说明第11号线路的连接端",
    "这个网络自身给母线电压设置了怎样的上下界？",
    "执行交流潮流并给出有功损耗",
    "沿用刚才结果列出负载率最高的五条线路",
    "对其中首位支路进行单一停运分析，报告原始指标和有来源的约束判断",
)
```

The scripted Pi must read `active_model.context_ref` from the injected view in turn 2, call `model.constraints.describe`, assert 0.94/1.06 came from the tool, submit the returned constraint evidence, reuse the registered power-flow result in turns 4–5, and call N-1 without policy.

- [ ] **Step 2: Add state and report assertions**

Assert one Pi process, five completed turns, replay equality, active IEEE-39 state, model constraints, calculation/scenario applicability, and no policy strings in trace/report/context. Assert the report puts each question and answer before context/trace detail and links every detailed trace page.

- [ ] **Step 3: Run E2E tests**

Run:

```bash
uv run --project packages/grid-agent pytest \
  packages/grid-agent/tests/e2e/test_continuous_analysis.py \
  packages/grid-agent/tests/e2e/test_semantic_pi_path.py -q
```

Expected: PASS without provider credentials or network access.

- [ ] **Step 4: Update the normative architecture document**

Document:

- the four layers: ledger kernel, capability catalog, typed domain state, bounded agent view;
- every `DomainState` record and `domain.state.projected` event;
- capability availability meanings;
- active versus historical result applicability;
- model/user/standard/task constraint sources;
- one worked held-out flow with concrete state transitions;
- compatible schema additions and replay rules;
- audit projection failures as advisory diagnostics.

Extend `test_analysis_context_docs.py` so every `EventType`, schema path, `domain_state`, and availability status is named in the document.

- [ ] **Step 5: Run the complete verification gate**

Run in order:

```bash
make doctor
make test
make test-e2e
make validate
```

Expected: all commands exit 0. `make validate-provider` is intentionally omitted because it can be billed and requires explicit credentials.

- [ ] **Step 6: Inspect one generated offline analysis report**

Run only the scripted E2E artifact generator already used by tests. Confirm manually/read-only that:

- questions and answers are immediately visible;
- each turn shows the active model and changed domain state;
- detailed input/output lives behind trace links;
- no long content IDs dominate the main narrative;
- no answer was changed by audit diagnostics.

- [ ] **Step 7: Commit**

```bash
git add docs/architecture/analysis-context.md \
  packages/grid-agent/tests/e2e \
  packages/grid-agent/tests/contract \
  schemas
git commit -m "test: verify general continuous pandapower context"
```

---

## Final Review Checklist

- [ ] `git status --short` contains only pre-existing user-owned changes and expected ignored run artifacts.
- [ ] `git log --oneline -8` shows one coherent commit per task; no implementation remains uncommitted.
- [ ] `rg` finds no legacy static policy semantics in runtime, skills, or validation.
- [ ] Capability availability distinguishes `not_published`, `not_applicable`, `unavailable`, and actual `failed` calls.
- [ ] IEEE-39 voltage bounds are simulator-backed 0.94–1.06 p.u., not project constants.
- [ ] N-1 retains raw metrics when constraints are absent and never invents violations.
- [ ] The analysis context retains historical artifacts while the injected view exposes only compatible active results.
- [ ] One Pi process carries ordered instructions; later prompts use structured active state rather than keyword answers.
- [ ] Reports remain reader-first and link detailed trajectories.
- [ ] Every claimed pass is supported by fresh command output.
