# Pandapower Static-Analysis Full-Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use test-driven development and execute this plan task-by-task. Steps use checkbox syntax for durable tracking.

**Goal:** Publish every in-scope pandapower 3.4.0 static-analysis capability through one contract-driven `gridctl`/Pi surface with complete result access and deterministic validation.

**Architecture:** Extend the existing content-addressed execution kernel with a versioned model/operation registry, immutable declarative revisions, schema-described network and result datasets, and family-specific pandapower bindings. Contracts remain the sole source for Pi tools; raw pandapower objects, Python and filesystem access never cross the simulator boundary.

**Tech Stack:** Python 3.12, pandapower 3.4.0, Pydantic 2, JSON Schema 2020-12, pytest 9, Node/Pi tool projection.

## Global Constraints

- Preserve `grid-capability` protocol version `1.0` and the single stdout answer envelope.
- All numerical/network claims cross `gridctl` and use current-run evidence.
- The release score is 100% of in-scope rows in `configs/capabilities/pandapower-3.4.0-static-analysis.json`.
- No question-specific branches, raw DataFrames, arbitrary callables, Python, shell or filesystem paths.
- Every production behavior follows RED → GREEN → refactor and adds single, composition and boundary coverage.
- Observation and validation remain advisory to primary execution.

---

### Task 1: Executable capability inventory and climb baseline

**Files:**
- Create: `tools/capability_matrix.py`
- Create: `packages/grid-simulator/tests/test_capability_matrix.py`
- Create: `docs/status/climb/*`
- Create: `tools/climb/*`
- Modify: `docs/status/INDEX.md`

**Interfaces:**
- Produces: `load_matrix(path) -> CapabilityMatrix`, `score_matrix(matrix, registry, tests) -> CoverageScore`
- Produces: `tools/climb/eval-local.sh` JSON with `total`, `per_task`, and gate status.

- [x] Write a failing test proving duplicate IDs, excluded rows with non-excluded status, unknown statuses and missing implementation evidence are rejected.
- [x] Run `uv run --project packages/grid-simulator pytest packages/grid-simulator/tests/test_capability_matrix.py -q` and verify the intended failure.
- [x] Implement the parser/scorer and a `--check` CLI that exits nonzero until all in-scope rows are published and verified.
- [x] Add the climb adapter and deterministic research-tree generation; record the baseline score without changing production capabilities.
- [x] Run the focused test and `tools/climb/eval-local.sh`.

### Task 2: Complete registered model catalog

**Files:**
- Create: `configs/models/pandapower-3.4.0-networks.json`
- Create: `tools/generate_pandapower_catalog.py`
- Modify: `packages/grid-simulator/src/grid_simulator/engine.py`
- Modify: `packages/grid-simulator/src/grid_simulator/models.py`
- Modify: `packages/grid-simulator/tests/test_models.py`

**Interfaces:**
- Produces: `RegisteredModel.factory: str`; `Pandapower340Engine.open_registered(factory_id: str)` resolves only the versioned allowlist.

- [x] Write failing tests that open case9, case14, case39 and a non-IEEE packaged network while rejecting unknown and argument-requiring factories.
- [x] Generate and review the zero-required-argument factory catalog from the pinned environment.
- [x] Implement catalog loading without `eval`, `getattr` on user input or filesystem input.
- [x] Verify deterministic fingerprints and run all model/context tests.

### Task 3: Universal schema-described network datasets and element resolution

**Files:**
- Replace internals: `packages/grid-simulator/src/grid_simulator/queries.py`
- Modify: `packages/grid-simulator/src/grid_simulator/operations.py`
- Add contracts: `model.dataset.list`, generalized describe/query and element get schemas
- Modify: `packages/grid-simulator/tests/test_datasets.py`

**Interfaces:**
- Produces: `NetworkDatasetCatalog.list/describe/query(net, revision_ref, request)`.
- Every returned field has type, unit, meaning, nullability and provenance.

- [x] Write failing parameterized tests over every non-empty static element table in case39 and representative specialized networks.
- [x] Implement scalar normalization, unit metadata, stable asset references, bounded predicates, sorting and paging.
- [x] Extend element resolution to every element table while preserving branch/bus aliases.
- [x] Verify unknown tables/fields/operators fail with typed errors and no raw object leaks.

### Task 4: Declarative creation and immutable revision derivation

**Files:**
- Create: `grid_simulator/creators.py`, `grid_simulator/revisions.py`
- Add contracts: `model.create`, `model.revision.derive`
- Create tests: `test_model_creation.py`, `test_revisions.py`

**Interfaces:**
- Produces: `CreatorRegistry.create(definition) -> net`; `RevisionStore.derive(parent, patches) -> OpenedContext`.

- [x] Write failing tests for a one-bus ext-grid short-circuit network, load scaling, branch outage, switch state, element creation and transactional rollback.
- [x] Implement a versioned creator registry with local symbolic reference resolution.
- [x] Implement allowlisted `set`, `scale`, `in_service`, `switch_state`, `create`, and referentially safe `drop` patches.
- [x] Persist derived revision/context lineage and verify parent artifacts remain byte-identical.

### Task 5: Complete analysis and result substrate

**Files:**
- Create: `grid_simulator/analysis_registry.py`, `grid_simulator/results.py`
- Refactor: `grid_simulator/analyses.py`, `grid_simulator/operations.py`
- Add contracts: `analysis.run`, `result.dataset.list/describe/query`, `result.aggregate`, `result.compare`
- Create tests: `test_analysis_registry.py`, `test_result_datasets.py`

**Interfaces:**
- Produces: `AnalysisRegistry.execute(operation, net, options) -> AnalysisOutcome`.
- Produces: `ResultStore.persist/load/list/describe/query/aggregate/compare`.

- [x] Write failing tests proving operation-specific schemas reject unknown options and callable/path injection.
- [x] Write failing tests proving every generated `res_*` table is persisted and queryable, including `res_ext_grid.p_mw`.
- [x] Implement the operation registry and generic scalar/table normalizer.
- [x] Make result identity independent of producer turn and add idempotent consumption lineage.
- [x] Verify bounded pages never truncate persisted full results.

### Task 6: Publish native static-analysis families

**Files:**
- Create binding modules under `grid_simulator/bindings/`
- Add/update family contracts and `capabilities/families.py`
- Create family tests under `packages/grid-simulator/tests/`

**Interfaces:**
- Registers: `powerflow.ac`, `powerflow.dc`, `powerflow.three_phase`, `opf.ac`, `opf.dc`, `short_circuit.iec60909`, `state_estimation.*`, `diagnostic.run`.

- [ ] Add RED/GREEN cycles for AC, DC and three-phase power flow with all documented native options.
- [ ] Add RED/GREEN cycles for AC/DC OPF including objective cost result tables and infeasibility outcomes.
- [ ] Add RED/GREEN cycles for IEC 60909 max/min, fault types, selected buses and branch results.
- [ ] Add RED/GREEN cycles for state estimation, observability/chi-square and bad-data removal.
- [ ] Add RED/GREEN cycles for diagnostics with normalized findings.

### Task 7: Complete topology, contingency, risk, equivalent and protection packages

**Files:**
- Create/refactor binding modules for topology, contingency, risk, equivalents and protection
- Add corresponding contracts and tests

**Interfaces:**
- Produces semantic topology paths/neighbors/unsupplied results, general contingency cases, constraint violations, ranked risk, derived equivalent revisions and static protection outcomes.

- [ ] Test and implement source-aware reachability and unsupplied bus detection.
- [ ] Generalize contingency selection across supported branch kinds and AC/DC evaluation.
- [ ] Implement typed violation evaluation and risk ranking from sourced constraints.
- [ ] Implement grid-equivalent derivation as a new revision with lineage.
- [ ] Implement supported static protection evaluation and typed prerequisites.

### Task 8: Contract-derived Pi surface, context and Skill

**Files:**
- Modify: `packages/grid-agent/src/grid_agent/tools/catalog.py`
- Modify: `packages/pi-grid-tools/src/domain-tools.mjs`
- Modify: `packages/grid-agent/src/grid_agent/analysis/projector.py`
- Modify: `skills/grid-static-analysis/`
- Modify tests in agent and Pi packages

**Interfaces:**
- Consumes only published capability contracts; no hand-maintained duplicate tool schemas.

- [ ] Write failing materialization tests for every published matrix row.
- [ ] Project model/revision/result lineage idempotently into bounded context.
- [ ] Generate package guidance and verify every operation/result dataset is discoverable.
- [ ] Prove no prohibited generic capability is exposed.

### Task 9: Semantic oracle and held-out validation

**Files:**
- Extend: `validation/run.py`, `validation/suites/`
- Add: `validation/suites/static-analysis-full/`
- Add oracle loader for `docs/test_script/测试题目答案.jsonl`
- Modify: `Makefile`, `docs/RUNBOOK.md`, `docs/MANUAL-VALIDATION.md`

**Interfaces:**
- Produces separate orchestration completion, semantic correctness, evidence and efficiency scores.

- [ ] Write failing evaluators for the seven acceptance questions and each matrix family.
- [ ] Add single-capability, composition, failure and held-out cases per in-scope row.
- [ ] Make `make validate` fail on semantic mismatch even when all turns submit answers.
- [ ] Keep provider validation optional and billed only when explicitly invoked.

### Task 10: Release closure

**Files:**
- Update matrix statuses from test evidence only
- Update active architecture/status/decision documentation
- Remove obsolete WP-A limitation guidance and tests

- [ ] Run focused family suites after every task.
- [ ] Run `make doctor`, `make test`, `make test-e2e`, `make validate` and the matrix checker.
- [ ] Run provider-backed `make analysis INSTRUCTIONS=validation/questions/test.md.txt` using the configured `.env` credentials.
- [ ] Inspect report, current-run evidence and semantic oracle; require all gates green.
- [ ] Commit coherent changes, regenerate climb state, refresh the active-session checkpoint, and verify no worktree or branch is left half-integrated.
