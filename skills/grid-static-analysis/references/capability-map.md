# Capability Map

## Use This For

Use this guide to choose exact published capability IDs and understand their safe composition sequence.

## Do Not Use This For

Do not use this as a substitute for executing a simulator capability when the answer needs network facts, numerical results, branch rankings, contingencies, or evidence. Do not call raw pandas, raw pandapower, arbitrary Python, shell commands, or filesystem paths.

## Concepts and Terminology

The model resolves user language such as "IEEE-39", "line 11", "highest loaded branches", or "N-1". The runtime validates typed inputs, reference formats, and evidence. Stable refs are opaque: `context_ref`, `revision_ref`, `asset_ref`, `dataset_ref`, `result_ref`, `artifact_ref`, and `evidence_ref`.

Source aliases such as `pandapower:line:11` are resolvable identifiers for user-facing lookup. Do not compose later calls from aliases when the prior capability returned a stable ref.

## Available Capabilities

- `environment.describe`: returns protocol, simulator, pandapower version, and executable capability catalog.
- `model.list`: lists supported registered models.
- `model.creator.list`: lists the complete pinned pandapower 3.4.0 element-creator allowlist and required arguments.
- `model.creator.describe`: describes one creator's signature, defaults, and local-reference arguments before construction.
- `model.create`: creates an immutable network from ordered allowlisted pandapower element creators and local element references.
- `context.open`: opens a supported model and creates a context with evidence.
- `context.get`: returns metadata for an existing context.
- `model.dataset.list`: lists every schema-described static network table in the active revision.
- `model.dataset.describe`: describes fields, types, units, nullability and provenance for a listed dataset.
- `model.dataset.query`: queries described fields with bounded filters, sorting and paging.
- `model.element.get`: resolves an element from any listed element table to `asset_ref`.
- `model.revision.derive`: applies transactional `scale`, `set`, `in_service`, `switch_state`, `create`, or referential `drop` patches and returns a new context without changing its parent.
- `model.equivalent.derive`: produces a Ward, extended-Ward, or REI equivalent as a new immutable context with explicit parent lineage.
- `model.constraints.describe`: returns voltage and loading constraints stored in the active model with their source fields.
- `topology.branch.endpoints.get`: returns branch endpoint buses and topology evidence.
- `topology.components.get`: returns connected component summaries.
- `analysis.operation.list`: lists published static analysis operations.
- `analysis.operation.describe`: returns the closed options schema for one operation.
- `analysis.run`: executes registered AC/DC/three-phase flow, AC/DC OPF, IEC 60909, state-estimation/chi-square/bad-data, or diagnostic operations; it returns a stable summary and persists every generated `res_*` table.
- `analysis.run` topology operations: `topology.path`, `topology.neighbors`, and `topology.unsupplied` persist queryable result tables.
- `analysis.run` protection operation: `protection.static` evaluates published protection devices against power-flow or short-circuit current results.
- `analysis.powerflow.ac.run`: runs AC steady-state power flow.
- `result.dataset.list`: lists all result tables stored under a `result_ref`.
- `result.dataset.describe`: reports result fields, types, units, nullability, and provenance.
- `result.dataset.query`: performs bounded select/filter/sort/page access without rerunning analysis.
- `result.aggregate`: computes bounded count/sum/min/max/average summaries.
- `result.compare`: aligns two result datasets by explicit keys and returns base/candidate/delta values.
- `analysis.result.violations.evaluate`: evaluates result fields only against constraints carried by the active model and persists `result.res_violation`.
- `analysis.result.risk.rank`: ranks a prior violation result with explicit/default severity weights and persists `result.res_risk`.
- `result.branches.rank`: ranks branch rows from a prior power-flow result.
- `analysis.contingency.n_minus_one.run`: runs isolated AC or DC single-branch outage scenarios.
- `evidence.get`: retrieves persisted evidence documents by `evidence_ref`.

## Parameters and Defaults

Catalog calls take no context. Model-specific calls require `context_ref`. Calculation calls require the same `context_ref` and contract-enumerated solver overrides only. Ranking requires an existing `result_ref`, explicit `metric`, `direction`, and `limit`.

Use `model.list` to select an exact model ID; `ieee39` remains the stable ID for case39. Before custom construction or a `create` patch, use `model.creator.list` and `model.creator.describe` instead of guessing a pandapower signature. N-1 requires the base context and stable branch refs.
For a model voltage range or branch loading limit, call `model.constraints.describe` with the active context. User criteria and named standards must remain separately identified sources.

## Result Fields and Units

The catalog reports capability IDs and tool names. Model context outputs include `model`, `engine`, `pandapower_version`, `source`, `semantic_sha256`, and element counts. Analysis outputs use `MW`, `percent`, and `p.u.` as specified by the producing capability.

## Single-step Examples

- Runtime readiness: call `environment.describe`.
- Supported models: call `model.list` with optional `family: "pandapower.networks"`.
- Existing context metadata: call `context.get` with `context_ref`.

## Multi-step Examples

- Endpoint answer: `context.open` -> `topology.branch.endpoints.get` -> cite `evidence_ref`.
- Generic result lookup: `context.open` -> `analysis.operation.describe` -> `analysis.run` -> `result.dataset.list` -> describe/query.
- Short circuit: open or create a model with IEC 60909 source/element parameters -> describe `short_circuit.iec60909` -> run -> query `result.res_bus_sc` and optional branch tables.
- State estimation: prepare model measurements -> run `state_estimation.estimate`; use the separately described chi-square and bad-data-removal operations when requested.
- OPF: ensure model flexibilities, constraints, and costs are present -> run `opf.ac` or `opf.dc` -> inspect `summary`, `result.res_objective`, and network result tables.
- Highest loaded lines: `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank`.
- Scenario delta: run the same operation on parent and derived contexts, then call `result.compare` with explicit dataset, keys, and fields.
- N-1 of critical branches: `context.open` -> resolve or rank branch refs -> `analysis.contingency.n_minus_one.run`.
- Network reduction: resolve boundary/internal bus refs -> `model.equivalent.derive` -> inspect the child context lineage -> run the requested analysis on the child.
- Sourced risk: run any compatible analysis -> `analysis.result.violations.evaluate` -> `analysis.result.risk.rank` -> query `result.res_risk`.

## Failures and Legal Recovery

For `model_not_found`, call `model.list`. For `unknown_creator` or `creator_arguments_invalid`, call `model.creator.list` then `model.creator.describe`. For `unknown_context`, call `context.open`. For `unknown_element` or `unknown_branch`, use `model.dataset.query` or `model.element.get`. For `unknown_result`, rerun the prerequisite power flow in the current workspace and use the new `result_ref`.

## Evidence Requirements

`context.open`, `topology.branch.endpoints.get`, `analysis.powerflow.ac.run`, `result.branches.rank`, and `analysis.contingency.n_minus_one.run` produce or require evidence-backed refs. Current-run evidence is required for final network facts and numerical claims.

## Common Mistakes

- Treating source aliases as stable references.
- Ranking without a prior `analysis.powerflow.ac.run`.
- Retrying non-convergence without changing a contract-supported solver setting or reporting the outcome.
- Guessing dataset fields instead of calling `model.dataset.list` and `model.dataset.describe`.
