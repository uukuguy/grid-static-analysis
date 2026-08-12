# Evidence And Recovery

## Use This For

Use this guide for topology evidence retrieval, current-run grounding, and legal recovery after capability errors.

## Do Not Use This For

Do not use this to create calculations, alter evidence, substitute missing evidence, inspect arbitrary files, or bypass the simulator workspace contract.

## Concepts and Terminology

Evidence references are opaque `evidence:sha256:*` values returned by trusted capabilities. A final answer may cite only evidence from the current run. `evidence.get` is topology/network-fact-only in WP-A: it retrieves persisted `network_fact` documents produced by `topology.branch.endpoints.get`; it does not validate user text, create new facts, or retrieve analysis result content.

## Available Capabilities

- `evidence.get`: input a topology endpoint `evidence_ref`; output `evidence_ref` and a `network_fact` document.

The document shape currently supports `evidence_type: "network_fact"`, `capability_id: "topology.branch.endpoints.get"`, `context_ref`, `revision_ref`, `subject_ref`, `facts`, and `provenance`.

## Parameters and Defaults

`evidence.get` requires a topology endpoint `evidence_ref`. There are no defaults and no path-like identifiers.

## Result Fields and Units

Endpoint evidence facts include `from_bus_ref` and `to_bus_ref`. Provenance includes `engine: "pandapower"`, `engine_version: "3.4.0"`, and `source_alias`.

## Single-step Examples

- "Show the topology endpoint evidence" -> call `evidence.get` with the `evidence_ref` returned by `topology.branch.endpoints.get`.
- "Can I cite this stale ref?" -> no, unless it came from the current run workspace.

## Multi-step Examples

- Endpoint answer with provenance: `context.open` -> `topology.branch.endpoints.get` -> `evidence.get` -> answer with buses plus evidence provenance.
- Failure report: if `artifact_unreadable`, preserve the original `evidence_ref` and state that the artifact could not be read.

## Failures and Legal Recovery

`unknown_evidence` means do not claim evidence; rerun the producing capability if the requested analysis is still required. `artifact_unreadable` means report unreadability and preserve the original reference. For `persist_failed`, do not claim that evidence exists. For `powerflow_non_converged`, report non-convergence or use a justified contract-supported solver change; do not blindly retry.

## Evidence Requirements

Evidence is required for topology endpoint claims, AC numerical claims, result rankings, and N-1 risk claims when the producing capability marks `evidence_required: true`. AC, ranking, and N-1 results must cite returned `result_ref` and `evidence_refs`; do not use `evidence.get` to request their result content.

## Common Mistakes

- Treating the existence of a ref-looking string as evidence.
- Reading files directly instead of using `evidence.get`.
- Omitting evidence when final answers include network-specific facts or numerical values.
- Calling `evidence.get` for AC, ranking, N-1, non-convergence, or contingency result content instead of citing returned refs.
