# Pandapower 3.4.0 Static-Analysis Full-Capability Design

**Date:** 2026-08-18  
**Status:** approved by product direction; implementation active  
**Supersedes:** every WP-A/WP-B deferral that treats a pandapower static-analysis family as future scope

## 1. Product objective

`grid-agent` must let an agent use the full pandapower 3.4.0 capability set that is relevant to static power-system analysis. Validation questions are probes of that surface; they never define the surface.

The implementation is complete only when every row marked `in_scope` in
`configs/capabilities/pandapower-3.4.0-static-analysis.json` is published,
executable through `gridctl`, projected to Pi from the same contracts, covered by
deterministic tests, and documented in the grid-analysis Skill.

## 2. Boundary

Full capability does not mean arbitrary code execution. The following invariants remain absolute:

1. Pandapower objects and DataFrames remain inside `gridctl`.
2. The model receives no shell, Python, filesystem path, callable name, raw object, or unrestricted table mutation.
3. Every model and result is content-addressed; every mutation creates an immutable revision.
4. Every numerical or network-specific claim is backed by current-run result/evidence references.
5. Pi tools are generated from versioned capability contracts; provider adapters are not parsed by analysis code.
6. Diagnostics and validation report defects but do not terminate otherwise valid agent execution.

Excluded modules are excluded because they are not static analysis or require an unpinned external runtime, not because they are deferred. Plotting, interactive presentation, generic file/database I/O, converters, arbitrary Python, time-series/control simulation, and optional Julia/PowerModels or power-grid-model backends are outside this product boundary.

## 3. Architecture

```text
Natural-language question
        |
        v
grid-agent / Pi
  - package discovery and guidance
  - contract-derived semantic tools
  - trajectory, context, answer submission
        |
        v  grid-capability 1.0
gridctl execution kernel
  - model catalog and immutable revisions
  - schema-described network datasets
  - operation registry and typed option validation
  - deterministic pandapower execution
  - complete result dataset store
  - evidence and typed domain outcomes
        |
        v
pandapower 3.4.0
```

The extension unit is a capability package, not a question-specific tool. A
package owns contracts, operation bindings, result schemas, evidence rules,
guidance, and validation cases.

## 4. Model and revision substrate

### 4.1 Registered models

The model catalog is generated from a versioned allowlist of zero-required-
argument factories in `pandapower.networks`. Runtime input is resolved only
against that allowlist; no function name is evaluated from user input.

Each entry records model ID, title, aliases, factory binding, engine version and
semantic fingerprint. IEEE cases and all other compatible packaged networks are
available through the same interface.

### 4.2 Declarative model creation

`model.create` accepts a bounded network definition whose element operations are
selected from a versioned element-creator registry. Each creator has a JSON
schema derived and reviewed for pandapower 3.4.0. References between newly
created elements use the explicit `{"element_ref":"<earlier_local_id>"}`
encoding and are resolved inside one transaction. `model.creator.describe`
publishes both the exact syntax and the ordering rule, so an agent never needs
to guess a raw index, `$ref` convention, or guide name.

This supports minimal networks, including one-bus short-circuit systems, without
registering fixtures for individual questions.

### 4.3 Immutable derivation

`model.revision.derive` accepts ordered typed patches:

- `set`: set allowlisted fields on selected elements;
- `scale`: multiply numeric fields on selected elements;
- `in_service`: place selected elements in or out of service;
- `switch_state`: open or close selected switches;
- `create`: add an element through the creator registry;
- `drop`: remove selected elements only after referential-integrity validation.

The parent revision never changes. Successful derivation writes a new network
artifact, revision reference and context. Invalid fields, selectors or topology
produce typed errors and no partial revision.

## 5. Dataset substrate

Network and result tables use the same three operations:

- `*.dataset.list` lists available datasets and row counts;
- `*.dataset.describe` returns fields, scalar types, units, meanings, nullability,
  origin and supported predicates;
- `*.dataset.query` performs bounded select/filter/sort/page operations using only
  fields returned by `describe`.

Network datasets cover every relevant pandapower element table. Result datasets
cover every `res_*` table created by the executed analysis, including ext_grid,
bus, line, transformer, generator, load, cost and short-circuit tables. Complete
results remain persisted even when the model-facing page is bounded.

`aggregate` and `compare` operate on stored datasets; they never rerun an
analysis implicitly.

## 6. Analysis operation registry

`analysis.run` is a contract-generated semantic union, not a generic function
dispatcher. Its `operation` field is an enum from the versioned registry and its
arguments are validated against the selected operation's schema before binding.
No callable/module/path can be supplied by the model.

The in-scope native operation families are:

- balanced AC power flow (`runpp`);
- DC power flow (`rundcpp`);
- unbalanced three-phase power flow (`runpp_3ph`);
- AC optimal power flow (`runopp`);
- DC optimal power flow (`rundcopp`);
- IEC 60909 short-circuit calculation (`shortcircuit.calc_sc`);
- state estimation, chi-square analysis and bad-data removal
  (`pandapower.estimation`);
- diagnostics (`pandapower.diagnostic`);
- topology and supply/reachability analysis;
- contingency and N-1 analysis;
- grid-equivalent construction;
- static protection evaluation supported by pandapower;
- model constraints, violation evaluation and risk ranking.

Every operation declares prerequisites, supported options, result tables,
domain-outcome errors, deterministic provenance and evidence facts.

## 7. Result and evidence model

An analysis result document contains:

- operation ID and normalized options;
- context and revision references;
- convergence/domain status;
- scalar summary facts;
- a manifest of all persisted result datasets;
- warnings and partial outcomes;
- pandapower/runtime provenance.

Result identity excludes turn ownership. Reusing an identical deterministic
result is idempotent: the original producer remains recorded and later turns add
consumption lineage rather than attempting to overwrite the result.

Evidence records the minimum claim-ready facts and links to the full result.
Queries over a result do not invent new simulator facts; derived aggregates and
comparisons are persisted as derived result documents with parent references.

## 8. Agent-facing surface

The model-facing surface is package-oriented and bounded:

- model discovery/open/create/derive;
- network dataset list/describe/query and element resolution;
- topology semantic operations;
- typed analysis operations;
- result dataset list/describe/query/aggregate/compare;
- evidence retrieval and answer submission.

Tool descriptions contain intended uses, inappropriate uses, prerequisites,
produced state, common next operations and typed recovery. The Skill explains
composition; it does not compensate for an incomplete schema.

## 9. Validation and release

The coverage matrix is executable product state. Release requires 100% of
`in_scope` rows to have:

- implementation status `published`;
- at least one contract test;
- at least one deterministic single-capability test;
- at least one composition test;
- at least one failure/boundary test;
- Pi materialization coverage;
- Skill coverage.

The seven questions under `docs/test_script/` are an acceptance slice. Their
answer file is a deterministic oracle, alongside existing TASK, static-core,
composition, recovery and held-out suites. `completed N/N` measures orchestration
completion only and is never reported as semantic correctness.

## 10. Non-goals

- No question-text branches.
- No per-network or per-question special-purpose calculation functions.
- No direct DataFrame, pandapowerNet or Python access.
- No silent fallback from DC to AC, OPF to power flow, or short circuit to a
  different analysis family.
- No validation rule may terminate a valid primary answer solely because a
  projection, summary, reference normalization or observer check disagrees.
