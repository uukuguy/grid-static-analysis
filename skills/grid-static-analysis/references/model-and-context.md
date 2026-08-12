# Model And Context

## Use This For

Use this guide for runtime discovery, supported model selection, context creation, and context metadata lookup with `environment.describe`, `model.list`, `context.open`, and `context.get`.

## Do Not Use This For

Do not use these capabilities for power-flow values, endpoint claims, branch ranking, contingencies, arbitrary model import, or model edits.

## Concepts and Terminology

WP-A supports one registered model: `ieee39`, sourced from `pandapower.networks.case39` under pandapower `3.4.0`. The model context is immutable and identified by `context_ref`. `context.open` also returns a semantic network hash and element counts.

## Available Capabilities

- `environment.describe`: inspect protocol `grid-capability`, protocol version `1.0`, simulator `grid-simulator`, pandapower version `3.4.0`, and executable capability catalog.
- `model.list`: list supported models, currently `ieee39`.
- `context.open`: input `model_id`; output `context_ref`, `model`, `engine`, `pandapower_version`, `source`, `semantic_sha256`, and counts.
- `context.get`: input `context_ref`; output `model` and counts for buses, lines, and transformers.

## Parameters and Defaults

`environment.describe` has no parameters. `model.list` optionally accepts `family: "pandapower.networks"`. `context.open` requires `model_id`. `context.get` requires `context_ref`.

## Result Fields and Units

Counts are integers: `buses`, `lines`, and `transformers`. `semantic_sha256` identifies the normalized model revision; it is not a numerical study result.

## Single-step Examples

- "What simulator is available?" -> call `environment.describe`.
- "Which models can I use?" -> call `model.list`.
- "Open IEEE-39" -> call `context.open` with `model_id: "ieee39"`.

## Multi-step Examples

- "Run AC flow on IEEE-39" -> `context.open` -> `analysis.powerflow.ac.run`.
- "How many lines are in the opened model?" -> `context.open` -> `context.get` if the context is already known.

## Failures and Legal Recovery

`catalog_unavailable` means report runtime discovery failure. `model_not_found` means call `model.list` and choose a supported model. `unknown_context` means reopen a supported model. `persist_failed` means report persistence failure rather than inventing a context.

## Evidence Requirements

`context.open` has `evidence_required: true` because opening creates the basis for later current-run claims. `environment.describe`, `model.list`, and `context.get` do not require evidence for generic catalog or metadata answers.

## Common Mistakes

- Claiming support for arbitrary MATPOWER, CIM, Excel, or user-uploaded files.
- Treating `context.get` as a way to open a model.
- Using old or external run refs in a new answer.
