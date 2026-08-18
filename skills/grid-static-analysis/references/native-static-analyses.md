# Native Static Analyses

## Use This For

Use `analysis.operation.list`, `analysis.operation.describe`, and `analysis.run` for every published pandapower static-analysis family. Operation discovery is authoritative; never infer an options schema from pandapower memory.

## Published Operations

- Power flow: `powerflow.ac`, `powerflow.dc`, `powerflow.three_phase`.
- Optimization: `opf.ac`, `opf.dc`.
- Short circuit: `short_circuit.iec60909`.
- State estimation: `state_estimation.estimate`, `state_estimation.chi2`, `state_estimation.remove_bad_data`.
- Diagnostics: `diagnostic.network`.
- Topology: `topology.path`, `topology.neighbors`, `topology.unsupplied`.
- Protection: `protection.static`.

Each successful call persists every generated public `res_*` table beneath its returned `result_ref`. Discover those tables with `result.dataset.list`; describe before query, aggregate, compare, or interpret.

## Prerequisites

OPF requires the model's flexibilities, limits, and costs. IEC 60909 requires short-circuit source and equipment parameters. State estimation requires measurements. Static protection requires a published protection device such as `protection_fuse`; use creator discovery and an immutable model creation/revision transaction. A missing prerequisite is a typed analysis outcome and must not be replaced with guessed values.

## Protection Modes

`protection.static` accepts `scenario: "pp"` for operating-current evaluation or `scenario: "sc"` for short-circuit evaluation. For short-circuit mode, select a contract-supported `fault` and `case`. Query `result.res_protection` for device outcomes.

## Evidence

Numerical conclusions must cite the current-run `result_ref` and the evidence refs returned by `analysis.run`. Result access capabilities do not authorize reading raw pandapower objects or arbitrary files.
