# Model And Context

## Use This For

Use this guide for runtime discovery, supported model selection, declarative creator discovery, model creation, immutable revision derivation, and context lookup with `environment.describe`, `model.list`, `model.creator.list`, `model.creator.describe`, `model.create`, `context.open`, `model.revision.derive`, and `context.get`.

## Do Not Use This For

Do not use these capabilities for power-flow values, endpoint claims, branch ranking, contingencies, arbitrary model import, or model edits.

## Concepts and Terminology

The runtime exposes a versioned allowlist of compatible zero-required-argument factories from `pandapower.networks` under pandapower `3.4.0`. `ieee39` is the stable product ID for `case39`; use `model.list` rather than assuming a model is present. A context is immutable and identified by `context_ref`.

## Available Capabilities

- `environment.describe`: inspect protocol `grid-capability`, protocol version `1.0`, simulator `grid-simulator`, pandapower version `3.4.0`, and executable capability catalog.
- `model.list`: list all supported registered models and their exact source factories.
- `model.creator.list`: list every pinned `pandapower.create` operation published by the runtime and its required arguments.
- `model.creator.describe`: inspect one creator's complete signature, defaults, and which arguments accept a prior local `element_ref`.
- `model.create`: create a new immutable model through ordered allowlisted creator operations; local `element_ref` values may reference earlier elements in the same transaction.
- `context.open`: input `model_id`; output `context_ref`, `model`, `engine`, `pandapower_version`, `source`, `semantic_sha256`, and counts.
- `context.get`: input `context_ref`; output `model` and counts for buses, lines, and transformers.
- `model.revision.derive`: create a child revision through typed `set`, `scale`, `in_service`, `switch_state`, `create`, and referential `drop` patches; failed patches leave the parent and workspace revision set unchanged.

## Parameters and Defaults

`environment.describe` and `model.creator.list` have no parameters. `model.creator.describe` requires the exact creator ID. `model.list` optionally accepts `family: "pandapower.networks"`. `context.open` requires `model_id`. `context.get` requires `context_ref`.

## Result Fields and Units

Counts are integers: `buses`, `lines`, and `transformers`. `semantic_sha256` identifies the normalized model revision; it is not a numerical study result.

## Single-step Examples

- "What simulator is available?" -> call `environment.describe`.
- "Which models can I use?" -> call `model.list`.
- "How do I add an asymmetric load?" -> `model.creator.list` -> `model.creator.describe` for the selected creator.
- "Open IEEE-39" -> call `context.open` with `model_id: "ieee39"`.
- "Open case9" -> first confirm `case9` in `model.list`, then call `context.open` with `model_id: "case9"`.

## Multi-step Examples

- "Run AC flow on IEEE-39" -> `context.open` -> `analysis.powerflow.ac.run`.
- "How many lines are in the opened model?" -> `context.open` -> `context.get` if the context is already known.

## Failures and Legal Recovery

`catalog_unavailable` means report runtime discovery failure. `model_not_found` means call `model.list` and choose a supported model. `unknown_creator` means call `model.creator.list`; `creator_arguments_invalid` means call `model.creator.describe`. `unknown_context` means reopen a supported model. `persist_failed` means report persistence failure rather than inventing a context.

## Evidence Requirements

`context.open` has `evidence_required: true` because opening creates the basis for later current-run claims. `environment.describe`, `model.list`, and `context.get` do not require evidence for generic catalog or metadata answers.

## Common Mistakes

- Claiming support for arbitrary MATPOWER, CIM, Excel, or user-uploaded files.
- Treating `context.get` as a way to open a model.
- Using old or external run refs in a new answer.
