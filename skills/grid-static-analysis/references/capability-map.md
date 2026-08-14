# Capability Map

## Use This For

Use this guide to choose the exact WP-A capability ID, understand the safe sequence, and separate available executable capabilities from defined future scope.

## Do Not Use This For

Do not use this as a substitute for executing a simulator capability when the answer needs network facts, numerical results, branch rankings, contingencies, or evidence. Do not call raw pandas, raw pandapower, arbitrary Python, shell commands, or filesystem paths.

## Concepts and Terminology

The model resolves user language such as "IEEE-39", "line 11", "highest loaded branches", or "N-1". The runtime validates typed inputs, reference formats, and evidence. Stable refs are opaque: `context_ref`, `revision_ref`, `asset_ref`, `dataset_ref`, `result_ref`, `artifact_ref`, and `evidence_ref`.

Source aliases such as `pandapower:line:11` are resolvable identifiers for user-facing lookup. Do not compose later calls from aliases when the prior capability returned a stable ref.

## Available Capabilities

- `environment.describe`: returns protocol, simulator, pandapower version, and executable capability catalog.
- `model.list`: lists supported registered models.
- `context.open`: opens a supported model and creates a context with evidence.
- `context.get`: returns metadata for an existing context.
- `model.dataset.describe`: describes supported network datasets and fields.
- `model.dataset.query`: queries curated bus or branch rows.
- `model.element.get`: resolves a bus, line, transformer, or three-winding transformer to `asset_ref`.
- `model.constraints.describe`: returns voltage and loading constraints stored in the active model with their source fields.
- `topology.branch.endpoints.get`: returns branch endpoint buses and topology evidence.
- `topology.components.get`: returns connected component summaries.
- `analysis.powerflow.ac.run`: runs AC steady-state power flow.
- `result.branches.rank`: ranks branch rows from a prior power-flow result.
- `analysis.contingency.n_minus_one.run`: runs isolated single-branch outage scenarios.
- `evidence.get`: retrieves persisted evidence documents by `evidence_ref`.

## Parameters and Defaults

Catalog calls take no context. Model-specific calls require `context_ref`. Calculation calls require the same `context_ref` and contract-enumerated solver overrides only. Ranking requires an existing `result_ref`, explicit `metric`, `direction`, and `limit`.

Use `model_id: "ieee39"` for the only registered WP-A model. N-1 requires the base context and stable branch refs.
For a model voltage range or branch loading limit, call `model.constraints.describe` with the active context. User criteria and named standards must remain separately identified sources.

## Result Fields and Units

The catalog reports capability IDs and tool names. Model context outputs include `model`, `engine`, `pandapower_version`, `source`, `semantic_sha256`, and element counts. Analysis outputs use `MW`, `percent`, and `p.u.` as specified by the producing capability.

## Single-step Examples

- Runtime readiness: call `environment.describe`.
- Supported models: call `model.list` with optional `family: "pandapower.networks"`.
- Existing context metadata: call `context.get` with `context_ref`.

## Multi-step Examples

- Endpoint answer: `context.open` -> `topology.branch.endpoints.get` -> cite `evidence_ref`.
- Highest loaded lines: `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank`.
- N-1 of critical branches: `context.open` -> resolve or rank branch refs -> `analysis.contingency.n_minus_one.run`.

## Failures and Legal Recovery

For `model_not_found`, call `model.list`. For `unknown_context`, call `context.open`. For `unknown_element` or `unknown_branch`, use `model.dataset.query` or `model.element.get`. For `unknown_result`, rerun the prerequisite power flow in the current workspace and use the new `result_ref`.

## Evidence Requirements

`context.open`, `topology.branch.endpoints.get`, `analysis.powerflow.ac.run`, `result.branches.rank`, and `analysis.contingency.n_minus_one.run` produce or require evidence-backed refs. Current-run evidence is required for final network facts and numerical claims.

## Common Mistakes

- Treating source aliases as stable references.
- Ranking without a prior `analysis.powerflow.ac.run`.
- Retrying non-convergence without changing a contract-supported solver setting or reporting the outcome.
- Promising unavailable future capabilities listed in `future-capabilities.md`.
