# Contingency Analysis

## Use This For

Use this guide for WP-A N-1 static security checks with `analysis.contingency.n_minus_one.run`.

## Do Not Use This For

Do not use this for dynamic stability, protection simulation, remedial action schemes, multi-element outages, OPF redispatch, or invented outage results.

## Concepts and Terminology

N-1 in WP-A means isolated single-branch outage screening. Each scenario starts from the same base `revision_ref`, uses a fresh isolated network copy, sets one stable branch out of service, runs AC power flow, and persists that scenario. The base context is never mutated.

Report `status` as `succeeded`, `partial`, or `failed`. A scenario can be `non_converged`; partial success is valid when some scenarios produce evidence and others do not converge.

## Available Capabilities

- `analysis.contingency.n_minus_one.run`: run deterministic single-branch outage checks for up to 32 branch refs under policy `static-analysis-v1`.

## Parameters and Defaults

Required: `context_ref`, `branch_refs`, and `policy: "static-analysis-v1"`.

`branch_refs` must contain 1 to 32 unique refs matching `asset:line:*`, `asset:trafo:*`, or `asset:trafo3w:*`.

Optional solver fields mirror AC power flow: `solver_profile: "ac-default-v1"`, `algorithm`, `calculate_voltage_angles`, `init`, `max_iteration`, `tolerance_mva`, `trafo_model`, `trafo_loading`, `enforce_q_lims`, `check_connectivity`.

Optional `violation_types`: `line_overload`, `bus_voltage_low`, `bus_voltage_high`, and `non_convergence`.

## Result Fields and Units

Outputs: `result_ref`, `context_ref`, `revision_ref`, `policy`, `status`, `solver`, `evidence_refs`, and `scenarios`.

Each scenario includes `scenario_result_ref`, `branch_ref`, `element_kind`, `pandapower_index`, `status`, `converged`, optional `max_loading_percent`, `violations`, and `evidence_ref`. Violation values use `percent` for loading and `p.u.` for bus voltage.

## Single-step Examples

- "Check N-1 for line 171" -> `context.open` -> resolve line 171 with `model.element.get` or endpoint lookup -> call `analysis.contingency.n_minus_one.run` with that branch ref and policy.

## Multi-step Examples

- "Rank critical lines then run N-1" -> `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank` for top N line refs -> `analysis.contingency.n_minus_one.run` using those stable refs.
- "Report low-voltage and overload risk" -> run N-1, group scenario violations by kind, cite scenario evidence, and explicitly include non-converged scenarios.

## Failures and Legal Recovery

`unknown_context` requires `context.open`. `unknown_branch` requires resolving with `model.element.get` or `topology.branch.endpoints.get`. `unsupported_policy` requires `static-analysis-v1`. `powerflow_non_converged` should be reported as non-convergence for the affected scenario or handled with a justified solver change. `powerflow_failed` and `persist_failed` must be reported without estimating results.

## Evidence Requirements

`analysis.contingency.n_minus_one.run` has `evidence_required: true`. Cite aggregate `result_ref`, aggregate `evidence_refs`, and scenario `evidence_ref` values for branch-specific risk claims. Submit the aggregate `result_ref` in `grid_submit_answer.result_refs`; include scenario result refs too when the answer relies on scenario-specific facts.

## Common Mistakes

- Mutating the base network across scenarios.
- Dropping failed or non-converged scenarios from the answer.
- Reusing branch aliases instead of stable branch refs.
- Treating N-1 as dynamic stability or corrective redispatch.
