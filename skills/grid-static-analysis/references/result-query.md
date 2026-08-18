# Result Query

## Use This For

Use this guide for complete persisted result access with `result.dataset.list`, `result.dataset.describe`, `result.dataset.query`, `result.aggregate`, `result.compare`, AC branch ranking with `result.branches.rank`, sourced violation/risk analysis, and deciding which returned references ground the answer.

## Do Not Use This For

Do not use result tools to run a new analysis, fabricate missing rows, read raw files, execute arbitrary expressions, or guess fields not returned by `describe`.

## Concepts and Terminology

`analysis.run` captures every generated pandapower `res_*` table under one content-addressed `result_ref`. Result tools consume that reference and never rerun the analysis. Dataset names preserve the source table, for example `result.res_bus` and `result.res_ext_grid`.

`result.branches.rank` consumes a prior current-run `result_ref` from the dedicated `analysis.powerflow.ac.run` contract. It remains a compatibility convenience for AC branch metrics.

`evidence.get` retrieves a current-run topology or analysis evidence document. A topology `network_fact` document supports a structural answer (for example, a line's two terminal buses); an analysis document supports a computed conclusion. It is useful for inspecting persisted facts and provenance, but it is not a substitute for result queries or a way to access arbitrary files.

## Available Capabilities

- `result.branches.rank`: rank branches by `loading_percent`, `p_from_mw`, `p_to_mw`, or `pl_mw`.
- `result.dataset.list`: list every captured `res_*` table and row count.
- `result.dataset.describe`: inspect fields and units before constructing a query.
- `result.dataset.query`: bounded select/filter/sort/page access.
- `result.aggregate`: count, sum, min, max, or average, optionally grouped by up to three fields.
- `result.compare`: compare identical datasets across two results using explicit key and value fields.
- `analysis.result.violations.evaluate`: consume a compatible `result_ref`, apply only model-sourced voltage/loading limits, and persist `result.res_violation` with deviations and constraint refs.
- `analysis.result.risk.rank`: consume a violation result, apply explicit/default severity weights to normalized exceedance, and persist `result.res_risk`.
- `evidence.get`: retrieve current-run topology or analysis evidence by its returned reference; do not use it to retrieve ranking rows.

## Parameters and Defaults

All generic result operations require persisted `result_ref` values and a dataset returned by `result.dataset.list`. Query fields, aggregate fields, comparison keys, and comparison values must exist in `result.dataset.describe`. Query and comparison limits are at most 100.

Required for ranking: `result_ref`, `metric`, `direction`, and `limit`. `limit` is 1 to 100. Optional `element_kind` filters to `line`, `trafo`, or `trafo3w`.

Metrics: `loading_percent`, `p_from_mw`, `p_to_mw`, and `pl_mw`. Direction: `ascending` or `descending`.

## Result Fields and Units

Outputs include `result_ref`, `context_ref`, `revision_ref`, `metric`, `metric_unit`, `direction`, and `branches`. Each branch includes `branch_ref`, `element_kind`, `pandapower_index`, `metric_value`, `unit`, `loading_percent`, `p_from_mw`, `p_to_mw`, and `pl_mw`. Units are `percent` or `MW`.

## Single-step Examples

- "Top 5 loaded lines" after power flow -> `result.branches.rank` with `metric: "loading_percent"`, `direction: "descending"`, `limit: 5`, `element_kind: "line"`.
- "Largest branch active losses" -> rank by `pl_mw` descending.
- "External-grid active power" -> list/describe/query `result.res_ext_grid`, selecting `index`, `asset_ref`, and `p_mw`.
- "Total served load" -> aggregate `p_mw` with `sum` over `result.res_load`.

## Multi-step Examples

- Full workflow: `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank` -> answer with ranked rows and `result_ref`.
- Generic workflow: `context.open` -> `analysis.operation.describe` -> `analysis.run` -> `result.dataset.list` -> `result.dataset.describe` -> query or aggregate.
- Revision comparison: run the same operation on parent and derived contexts -> `result.compare` with `key_fields: ["index"]` and explicit fields.
- Critical-contingency workflow: rank top loaded branches, then pass their `branch_ref` values to `analysis.contingency.n_minus_one.run`.
- Constraint workflow: run analysis -> evaluate violations -> rank risk -> query `result.res_violation` or `result.res_risk`; keep the source and derived result refs distinct.

## Failures and Legal Recovery

`unknown_result` means run `analysis.powerflow.ac.run` first in the current workspace. `result_integrity_failed` means rerun AC power flow and use the new `result_ref`. `invalid_metric` means choose one of the four contract metrics. `invalid_limit` means choose 1 to 100.

## Evidence Requirements

`result.branches.rank` has `evidence_required: true` because it depends on persisted AC result references. Cite the input `result_ref` and relevant `evidence_refs` from the producing power-flow result. Submit that primary `result_ref` in `grid_submit_answer.result_refs`. AC, ranking, and N-1 results must cite returned `result_ref` and `evidence_refs`; `evidence.get` may inspect their persisted evidence when needed.

## Common Mistakes

- Calling ranking with a context ref instead of a result ref.
- Ranking a metric that was not produced by AC power flow.
- Answering "highest loaded" from static line ratings instead of power-flow result rows.
- Calling `evidence.get` to retrieve ranking rows rather than using `result.branches.rank`.
