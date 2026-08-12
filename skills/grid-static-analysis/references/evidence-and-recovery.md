# Evidence And Recovery

## Use This For

Use this guide for evidence retrieval, current-run grounding, and legal recovery after capability errors.

## Do Not Use This For

Do not use this to create calculations, alter evidence, substitute missing evidence, inspect arbitrary files, or bypass the simulator workspace contract.

## Concepts and Terminology

Evidence references are opaque `evidence:sha256:*` values returned by trusted capabilities. A final answer may cite only evidence from the current run. `evidence.get` retrieves a persisted evidence document; it does not validate user text and does not create new facts.

## Available Capabilities

- `evidence.get`: input `evidence_ref`; output `evidence_ref` and `document`.

The document shape currently supports `evidence_type: "network_fact"`, `capability_id: "topology.branch.endpoints.get"`, `context_ref`, `revision_ref`, `subject_ref`, `facts`, and `provenance`.

## Parameters and Defaults

`evidence.get` requires `evidence_ref`. There are no defaults and no path-like identifiers.

## Result Fields and Units

Endpoint evidence facts include `from_bus_ref` and `to_bus_ref`. Provenance includes `engine: "pandapower"`, `engine_version: "3.4.0"`, and `source_alias`.

## Single-step Examples

- "Show the evidence for this endpoint result" -> call `evidence.get` with the returned `evidence_ref`.
- "Can I cite this stale ref?" -> no, unless it came from the current run workspace.

## Multi-step Examples

- Endpoint answer with evidence body: `context.open` -> `topology.branch.endpoints.get` -> `evidence.get` -> answer with buses plus evidence provenance.
- Failure report: if `artifact_unreadable`, preserve the original `evidence_ref` and state that the artifact could not be read.

## Failures and Legal Recovery

`unknown_evidence` means do not claim evidence; rerun the producing capability if the requested analysis is still required. `artifact_unreadable` means report unreadability and preserve the original reference. For `persist_failed`, do not claim that evidence exists. For `powerflow_non_converged`, report non-convergence or use a justified contract-supported solver change; do not blindly retry.

## Evidence Requirements

Evidence is required for topology endpoint claims, AC numerical claims, result rankings, and N-1 risk claims when the producing capability marks `evidence_required: true`.

## Common Mistakes

- Treating the existence of a ref-looking string as evidence.
- Reading files directly instead of using `evidence.get`.
- Omitting evidence when final answers include network-specific facts or numerical values.
