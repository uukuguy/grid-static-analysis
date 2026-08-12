# Future Capabilities

## Use This For

Use this guide to answer scope questions and avoid promising capabilities that are defined as future work but unavailable in WP-A.

## Do Not Use This For

Do not use this as permission to simulate unsupported studies, import user models, modify networks, run raw pandapower, or infer unavailable results.

## Concepts and Terminology

Unavailable means there is no advertised executable WP-A capability ID for the workflow. The agent may explain the limitation and, when useful, suggest the closest available WP-A workflow without changing the user's requested study type.

## Available Capabilities

There are no executable future capabilities in WP-A. Available alternatives are limited to the current capability map: `environment.describe`, `model.list`, `context.open`, `context.get`, `model.dataset.describe`, `model.dataset.query`, `model.element.get`, `topology.branch.endpoints.get`, `topology.components.get`, `analysis.powerflow.ac.run`, `result.branches.rank`, `analysis.contingency.n_minus_one.run`, and `evidence.get`.

Unavailable in WP-A:

- DC flow.
- OPF and security-constrained OPF.
- Short circuit.
- State estimation.
- Time series.
- Model import, create, edit, or delete.
- Topology switching or branch status modification outside isolated N-1 scenarios.
- Richer policy/risk engines beyond `static-analysis-v1`.
- Multiple registered networks beyond `ieee39`.
- Dynamic stability, protection relay simulation, and remedial action optimization.

## Parameters and Defaults

No parameters exist for unavailable capabilities. Do not invent capability IDs or schemas.

## Result Fields and Units

No result fields or units exist for unavailable capabilities. Any value would be unsupported unless produced by an available WP-A capability.

## Single-step Examples

- "Run DC power flow" -> explain that DC flow is unavailable in WP-A; offer AC power flow with `analysis.powerflow.ac.run` only if acceptable.
- "Import my model" -> explain that only registered `ieee39` is supported.

## Multi-step Examples

- "Do short-circuit then rank risk" -> state short circuit is unavailable; if the user wants static AC security instead, use `context.open` -> `analysis.powerflow.ac.run` -> `result.branches.rank` or N-1.

## Failures and Legal Recovery

If the user asks for unavailable scope, do not emulate it with a different calculation without saying so. Ask for permission only when a nearby available workflow would materially change the requested analysis.

## Evidence Requirements

Unavailable workflows produce no evidence. Do not claim evidence for future capabilities.

## Common Mistakes

- Presenting AC power flow as DC flow.
- Treating N-1 as OPF or dynamic stability.
- Claiming support for multiple networks because pandapower has many examples; WP-A registers only `ieee39`.
