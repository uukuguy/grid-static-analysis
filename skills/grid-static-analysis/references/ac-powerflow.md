# AC Powerflow

## Use This For

Use this guide for steady-state AC load flow, active loss, branch loading, and prerequisite results for ranking or contingency analysis with `analysis.powerflow.ac.run`.

## Do Not Use This For

Do not use this for DC approximation, OPF, short circuit, dynamic simulation, state estimation, time series, or guessed numerical answers.

## Concepts and Terminology

AC power flow requires an opened immutable context and a solver profile. The default profile is `ac-default-v1`; solver overrides must be the explicit fields allowed by the contract. Always check the returned `converged` value. Non-convergence is an outcome to report or analyze, not a value to repair by text.

Pandapower `runpp` supports algorithms including Newton-Raphson, Iwamoto Newton-Raphson, and backward/forward sweep. WP-A exposes only `nr`, `iwamoto_nr`, and `bfsw` through the typed contract.

## Available Capabilities

- `analysis.powerflow.ac.run`: run pandapower 3.4.0 AC load flow on an immutable context and persist a normalized result artifact.

## Parameters and Defaults

Required: `context_ref`.

Optional: `solver_profile: "ac-default-v1"`, `algorithm` in `nr`, `iwamoto_nr`, or `bfsw`; `calculate_voltage_angles`; `init` in `auto`, `flat`, `dc`, or `results`; `max_iteration` from 1 to 100; `tolerance_mva` greater than 0 up to 1; `trafo_model` in `t` or `pi`; `trafo_loading` in `current` or `power`; `enforce_q_lims`; `check_connectivity`.

Use defaults unless the user requests a solver choice or recovery requires a contract-supported change.

## Result Fields and Units

Outputs: `result_ref`, `context_ref`, `revision_ref`, `converged`, `solver`, `total_active_loss`, and `evidence_refs`. `total_active_loss.value` is in `MW`. Branch loading exposed through downstream ranking is in `percent`; branch active powers and losses are in `MW`.

## Single-step Examples

- "Run AC power flow and output active loss" -> `context.open` -> `analysis.powerflow.ac.run`; answer with `total_active_loss.value`, `MW`, `converged`, `result_ref`, and evidence refs.
- "Use Iwamoto Newton-Raphson" -> include `algorithm: "iwamoto_nr"` while preserving the context.

## Multi-step Examples

- Highest loaded branches: `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank` with `metric: "loading_percent"`, `direction: "descending"`.
- Contingency screening after base case: `context.open` -> `analysis.powerflow.ac.run` for base evidence if requested -> resolve branch refs -> `analysis.contingency.n_minus_one.run`.

## Failures and Legal Recovery

`unknown_context` requires `context.open`. `powerflow_non_converged` means report non-convergence, inspect allowed diagnostics if available, or change a contract-supported solver option such as `algorithm` or `init` when justified. Do not blindly retry the same call. `powerflow_failed` means report failure instead of estimating values. `persist_failed` means no result claim can be made.

## Evidence Requirements

`analysis.powerflow.ac.run` has `evidence_required: true`. Any numerical AC claim must reference the current-run `result_ref` and returned `evidence_refs`.

## Common Mistakes

- Ranking lines without using the returned `result_ref`.
- Omitting convergence status.
- Treating topology endpoints as power-flow direction.
- Using solver options outside the contract.
