# Network Elements

## Use This For

Use this guide for resolving user-described buses, lines, transformers, and datasets with `model.element.get`, `model.dataset.describe`, and `model.dataset.query`.

## Do Not Use This For

Do not use dataset queries for result tables, branch loading rankings, raw table access, DataFrame expressions, model mutation, or arbitrary file inspection.

## Concepts and Terminology

Elements have a `kind`: `bus`, `line`, `trafo`, or `trafo3w`. Resolution namespaces are `pandapower_index`, `name`, `alias`, and `asset_ref`. A source alias such as `pandapower:line:11` is useful for recognition; a returned `asset_ref` is the stable identifier to pass to topology, ranking follow-up, or contingency calls.

## Available Capabilities

- `model.element.get`: resolve one element from `context_ref`, `kind`, `namespace`, and `identifier`.
- `model.dataset.describe`: describe `network.buses` or `network.branches`, including selectable fields and row count.
- `model.dataset.query`: query curated rows from `network.buses` or `network.branches`.

## Parameters and Defaults

`model.element.get` requires `context_ref`, `kind`, `namespace`, and `identifier`. For a user phrase "line 11", use `kind: "line"`, `namespace: "pandapower_index"`, and `identifier: "11"` unless prior context indicates a stable `asset_ref`.

`model.dataset.describe` requires `context_ref` and `dataset`, where `dataset` is `network.buses` or `network.branches`.

`model.dataset.query` requires `context_ref`, `dataset`, and `select`. `select` accepts up to 16 fields. Optional `where` supports `kind`, `in_service`, `name`, `alias`, and `asset_ref`. Optional `sort` requires `field` and `direction`. Optional `limit` is 1 to 200.

Bus fields: `asset_ref`, `kind`, `index`, `name`, `alias`, `vn_kv`, `in_service`.

Branch fields: `asset_ref`, `kind`, `index`, `name`, `alias`, `from_bus_ref`, `to_bus_ref`, `from_bus_index`, `to_bus_index`, `from_bus_name`, `to_bus_name`, `in_service`, `length_km`, `max_i_ka`.

## Result Fields and Units

`vn_kv` is kV. `length_km` is km. `max_i_ka` is kA. Dataset outputs include `dataset_ref`, `context_ref`, `revision_ref`, `row_count`, `returned_row_count`, optional `artifact_ref`, and `rows`.

## Single-step Examples

- Resolve line 11: `model.element.get` with `kind: "line"`, `namespace: "pandapower_index"`, `identifier: "11"`.
- List branch aliases: `model.dataset.query` on `network.branches` selecting `kind`, `index`, `alias`, `asset_ref`, with an appropriate `limit`.
- Describe bus fields: `model.dataset.describe` with `dataset: "network.buses"`.

## Multi-step Examples

- Endpoint question: `context.open` -> `model.element.get` -> `topology.branch.endpoints.get` using the returned `asset_ref`.
- N-1 on named lines: `context.open` -> resolve each line with `model.element.get` -> pass branch refs to `analysis.contingency.n_minus_one.run`.

## Failures and Legal Recovery

`unknown_context` requires `context.open`. `unsupported_element` requires choosing `bus`, `line`, `trafo`, or `trafo3w`. `invalid_query` means correct the namespace and identifier shape. `unknown_element` means inspect available rows with `model.dataset.query`. `unsupported_dataset` means choose `network.buses` or `network.branches`. `field_unavailable`, `where_field_unavailable`, or `sort_field_unselected` means correct the selected fields.

## Evidence Requirements

Element and dataset lookup capabilities do not themselves require evidence. If their result supports a final topology or calculation claim, pair it with evidence from the downstream topology or analysis capability.

## Common Mistakes

- Using dataset rows as if they were post-power-flow results.
- Passing a source alias where a stable `asset_ref` is available.
- Selecting branch-only fields from `network.buses` or bus-only fields from `network.branches`.
