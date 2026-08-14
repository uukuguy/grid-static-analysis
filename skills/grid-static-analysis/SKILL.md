---
name: grid-static-analysis
description: Analyze registered power-system networks with pandapower 3.4.0 domain tools. Use for network data, topology, AC power flow, branch ranking, N-1 contingencies, result interpretation, and evidence-backed grid conclusions.
---

# Grid Static Analysis

## Operating Rules

Use this Skill when a user asks about a registered power-system model, network facts, topology, AC steady-state power flow, branch ranking, N-1 static contingencies, result interpretation, or evidence-backed grid conclusions.

The model resolves natural language, entity names, aliases, and analysis intent. The framework validates typed capability calls, argument schemas, current-run references, and evidence. Do not treat the model's text recognition as validation.

Separate answer types:

- Knowledge answers explain capability concepts without simulator evidence when no network-specific fact or numerical result is claimed.
- Network facts come from registered model capabilities and require a current context. Topology facts that return `evidence_ref` must cite that evidence.
- Calculation results come only from simulator analysis capabilities and must cite current-run `result_ref` and `evidence_refs`.

`evidence.get` is topology/network-fact-only in WP-A. It retrieves `network_fact` documents produced by `topology.branch.endpoints.get`; AC, ranking, and N-1 results must cite returned `result_ref` and `evidence_refs` rather than asking `evidence.get` for analysis result documents.

Never invent voltages, flows, losses, rankings, overloads, contingency outcomes, or evidence. Do not use raw pandas, raw pandapower objects, arbitrary Python, shell commands, or filesystem paths as model capabilities. Use only the typed grid capabilities exposed by the runtime.

## Choose the Analysis Domain

- Model and runtime catalog: [capability-map](references/capability-map.md), [model-and-context](references/model-and-context.md).
- Network elements and datasets: [network-elements](references/network-elements.md).
- Topology endpoints and components: [topology-analysis](references/topology-analysis.md).
- AC power flow and solver profile: [ac-powerflow](references/ac-powerflow.md).
- N-1 static contingency: [contingency-analysis](references/contingency-analysis.md).
- Model-owned voltage and loading limits: `model.constraints.describe` with the active `context_ref`; identify model, user, or named-standard sources explicitly.
- Result ranking and evidence retrieval: [result-query](references/result-query.md), [evidence-and-recovery](references/evidence-and-recovery.md).
- Defined future scope that is unavailable in WP-A: [future-capabilities](references/future-capabilities.md).

## Context and Evidence Discipline

Open a context with `context.open` before model-specific operations. Use the returned `context_ref` for every later call. Treat `revision_ref`, `asset_ref`, `dataset_ref`, `result_ref`, `artifact_ref`, and `evidence_ref` as opaque stable references. Source aliases such as `pandapower:line:11` help resolve user language, but stable refs are used for composition.

Only cite evidence that exists in the current run. If a capability says `evidence_required: true`, final network-specific claims must include the returned evidence or result reference. Submit final answers with `grid_submit_answer` using separate `result_refs` (the primary result(s) used for the conclusion) and `claim_evidence_refs` arrays. The verifier also follows and verifies result references already bound into claimed analysis evidence, so do not repeat every scenario result merely to satisfy a format rule. Use `result_refs: []` only for topology-only or limitation answers with no persisted result. Offline informational answers may not create run workspaces or imply simulator evidence.

## Simple Questions

For capability questions, answer from the Skill and knowledge documents. A numerical operating range requires an active model constraint, user criterion, or explicitly named standard. For supported model lists, use `environment.describe` or `model.list` if a runtime-backed answer is required.

For "Which buses does line 11 connect?", open `ieee39` with `context.open`, resolve line 11 with `model.element.get` or directly call `topology.branch.endpoints.get` using `kind: line`, `namespace: pandapower_index`, `identifier: "11"`, then answer from `from_bus`, `to_bus`, and `evidence_ref`.

For "What fields can this tool take?", prefer the exact contract in the relevant reference and name the capability ID.

## Multi-step Analysis

Plan from stable references:

1. Discover runtime and model support with `environment.describe` or `model.list`.
2. Open the model once with `context.open`.
3. Resolve requested buses, lines, transformers, or datasets with `model.element.get`, `model.dataset.describe`, or `model.dataset.query`.
4. Run `analysis.powerflow.ac.run` for numerical AC steady-state values.
5. Rank existing branch results with `result.branches.rank`; do not rerun power flow for ranking.
6. Run `analysis.contingency.n_minus_one.run` for requested branch outages from the same base context; interpret violations only against returned model constraints.
7. Use `evidence.get` to inspect a current-run topology or analysis document when its persisted facts are needed. For AC, ranking, and N-1, cite the returned primary `result_ref` and relevant `evidence_refs`; scenario results linked by claimed N-1 evidence are verified automatically.

## Failure Recovery

If an element, context, result, metric, or dataset is unknown, use the recovery action named by the failing capability. Do not guess missing refs. Non-convergence is a valid simulator outcome, not a reason to fabricate numbers or blindly retry. A solver change is legal only when the user asked for that analysis and the change is within the contract.

If evidence cannot be read, preserve the original reference and report the artifact problem. If persistence fails, report the failure and avoid claiming a calculation result.

## Capability Status

Available WP-A executable capabilities: `environment.describe`, `model.list`, `context.open`, `context.get`, `model.dataset.describe`, `model.dataset.query`, `model.element.get`, `model.constraints.describe`, `topology.branch.endpoints.get`, `topology.components.get`, `analysis.powerflow.ac.run`, `result.branches.rank`, `analysis.contingency.n_minus_one.run`, and `evidence.get`.

Defined but unavailable future capabilities include DC flow, OPF, short circuit, state estimation, time series, model import/create/modify, richer sourced risk engines, and multiple registered networks. See [future-capabilities](references/future-capabilities.md) before promising those workflows.
