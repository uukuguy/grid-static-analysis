# Result Query

## Use This For

Use this guide for ranking branch rows from a persisted AC result with `result.branches.rank` and for deciding which returned references ground the answer.

## Do Not Use This For

Do not use ranking to run a new power flow, fabricate missing result rows, query raw result tables, or rank metrics not in the contract.

## Concepts and Terminology

`result.branches.rank` consumes a prior current-run `result_ref` from `analysis.powerflow.ac.run`. It must not rerun power flow. Ranking is a read-only result query over persisted analysis artifacts.

`evidence.get` is topology/network-fact-only in WP-A. It retrieves `network_fact` documents from `topology.branch.endpoints.get`; it is not the way to fetch AC, ranking, or N-1 result content.

## Available Capabilities

- `result.branches.rank`: rank branches by `loading_percent`, `p_from_mw`, `p_to_mw`, or `pl_mw`.
- `evidence.get`: retrieve topology endpoint `network_fact` documents only; do not use it to retrieve ranking rows or analysis result content.

## Parameters and Defaults

Required for ranking: `result_ref`, `metric`, `direction`, and `limit`. `limit` is 1 to 100. Optional `element_kind` filters to `line`, `trafo`, or `trafo3w`.

Metrics: `loading_percent`, `p_from_mw`, `p_to_mw`, and `pl_mw`. Direction: `ascending` or `descending`.

## Result Fields and Units

Outputs include `result_ref`, `context_ref`, `revision_ref`, `metric`, `metric_unit`, `direction`, and `branches`. Each branch includes `branch_ref`, `element_kind`, `pandapower_index`, `metric_value`, `unit`, `loading_percent`, `p_from_mw`, `p_to_mw`, and `pl_mw`. Units are `percent` or `MW`.

## Single-step Examples

- "Top 5 loaded lines" after power flow -> `result.branches.rank` with `metric: "loading_percent"`, `direction: "descending"`, `limit: 5`, `element_kind: "line"`.
- "Largest branch active losses" -> rank by `pl_mw` descending.

## Multi-step Examples

- Full workflow: `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank` -> answer with ranked rows and `result_ref`.
- Critical-contingency workflow: rank top loaded branches, then pass their `branch_ref` values to `analysis.contingency.n_minus_one.run`.

## Failures and Legal Recovery

`unknown_result` means run `analysis.powerflow.ac.run` first in the current workspace. `result_integrity_failed` means rerun AC power flow and use the new `result_ref`. `invalid_metric` means choose one of the four contract metrics. `invalid_limit` means choose 1 to 100.

## Evidence Requirements

`result.branches.rank` has `evidence_required: true` because it depends on persisted AC result references. Cite the input `result_ref` and relevant `evidence_refs` from the producing power-flow result. Submit that `result_ref` in `grid_submit_answer.result_refs`. AC, ranking, and N-1 results must cite returned `result_ref` and `evidence_refs`; only topology endpoint `network_fact` documents are read through `evidence.get`.

## Common Mistakes

- Calling ranking with a context ref instead of a result ref.
- Ranking a metric that was not produced by AC power flow.
- Answering "highest loaded" from static line ratings instead of power-flow result rows.
- Calling `evidence.get` to retrieve ranking rows or AC/N-1 result content.
