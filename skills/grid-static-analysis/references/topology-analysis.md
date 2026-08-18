# Topology Analysis

## Use This For

Use this guide for source-model branch endpoints, connected components, shortest paths, bounded neighborhoods, and unsupplied buses.

## Do Not Use This For

Do not use topology endpoints as real-time flow direction, power-flow magnitude, branch loading, outage result, dynamic islanding, or AC reachability under contingency.

## Concepts and Terminology

Topology endpoints are the source model's branch table endpoints. `from_bus` and `to_bus` name table orientation, not real-time active-power direction. Pandapower topology conversion represents in-service buses as graph nodes and physical connections as graph edges; WP-A uses this only through typed capabilities.

## Available Capabilities

- `topology.branch.endpoints.get`: returns a branch object, `from_bus`, `to_bus`, `context_ref`, `revision_ref`, and `evidence_ref`.
- `topology.components.get`: returns `component_count` and up to 50 component summaries with `component_id`, `bus_count`, `branch_count`, and `bus_refs`.
- `analysis.run` with `topology.path`: returns a queryable ordered bus path in `result.res_topology_path`.
- `analysis.run` with `topology.neighbors`: returns buses and hop depths in `result.res_topology_neighbor`.
- `analysis.run` with `topology.unsupplied`: returns unsupplied buses in `result.res_unsupplied_bus`.

## Parameters and Defaults

`topology.branch.endpoints.get` requires `context_ref` and one of two addressing modes: either `branch_ref`, or the triple `kind`, `namespace`, and `identifier`. Supported branch kinds are `line`, `trafo`, and `trafo3w`. Namespaces are `pandapower_index`, `name`, `alias`, and `asset_ref`.

`topology.components.get` requires only `context_ref`.

## Result Fields and Units

Endpoint outputs contain branch `asset_ref`, `kind`, `index`, `name`, and `alias`; each endpoint bus contains `asset_ref`, `index`, `name`, and `alias`. Components report counts and bus refs; no electrical units or flow values are produced.

## Single-step Examples

- "Line 11 connects which buses?" -> `topology.branch.endpoints.get` with `kind: "line"`, `namespace: "pandapower_index"`, `identifier: "11"`, after opening context.
- "How many islands are in this model?" -> `topology.components.get` with the current `context_ref`.
- "Which buses are within two hops?" -> describe and run `topology.neighbors`, then query `result.res_topology_neighbor`.

## Multi-step Examples

- Verify a contingency target: `context.open` -> `topology.branch.endpoints.get` -> pass `branch.asset_ref` to `analysis.contingency.n_minus_one.run`.
- Inspect topology before AC: `context.open` -> `topology.components.get` -> if topology is acceptable, run `analysis.powerflow.ac.run`.

## Failures and Legal Recovery

`unknown_context` requires opening a supported model. `unknown_branch` means resolve the branch with `model.element.get` or inspect `network.branches`. `unsupported_branch_kind` means use `line`, `trafo`, or `trafo3w`. `topology_unavailable` means report that components could not be derived. `evidence_persist_failed` means do not claim endpoint evidence; retry only after workspace persistence is healthy.

## Evidence Requirements

`topology.branch.endpoints.get` has `evidence_required: true`; cite its `evidence_ref` for endpoint claims. `topology.components.get` does not require evidence, but still requires a valid current `context_ref`.

## Common Mistakes

- Saying power flows from `from_bus` to `to_bus` based only on endpoint orientation.
- Answering endpoint questions from memory or docs without a current context.
- Mutating line status to infer components; WP-A topology calls are read-only.
