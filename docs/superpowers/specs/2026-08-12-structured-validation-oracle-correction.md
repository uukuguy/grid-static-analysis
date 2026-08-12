# Structured Validation Oracle Correction

## Decision

Validation separates answering from assessment.

- The model interprets a user's language, resolves domain entities, chooses the relevant domain capabilities, composes calls, and writes `answer_output`.
- The framework exposes typed tool results, result/evidence references, and a current-run trace.
- The validator assesses simulator-backed claims only from those structured execution facts. It does not extract entities, identifiers, units, or relationships from `answer_output`.

This corrects the initial WP-A validation draft, which proposed a text-based `branch_endpoints` oracle. That approach would create a second, fragile natural-language recognizer in the framework and is therefore prohibited.

## Structured Oracle Contract

A structured validation case declares:

```json
{
  "oracle": {
    "kind": "structured",
    "evaluator": "topology_branch_endpoints",
    "arguments": {
      "capability": "topology.branch.endpoints.get",
      "branch": {
        "kind": "line",
        "namespace": "pandapower_index",
        "identifier": "11"
      },
      "from_bus": {"name": "6"},
      "to_bus": {"name": "11"}
    }
  }
}
```

The run trace records one tool-result event per completed domain call. A tool-result event contains `capability`, a typed `result`, and any `evidence_refs`. The validator selects successful events matching the declared capability and subject, then compares the declared result fields exactly. Endpoint order is preserved unless a future capability contract expressly declares an unordered relationship.

The final CLI envelope remains `{question_id, answer_output}`. The validator checks that envelope and requires a non-empty answer, but does not use its wording to decide whether a network fact is true.

## Failure Classes

- `verification_trace_missing`: a case requiring structured facts did not supply a current-run trace.
- `verification_result_missing`: the trace has no successful matching tool-result event.
- `verification_evidence_missing`: a case requiring evidence has no evidence reference associated with the matching event.
- `structured_oracle_mismatch`: a matching result exists but its declared factual fields differ from the case expectation.

These are deterministic validation outcomes. They do not attempt a text fallback and they do not ask the framework to recognize entities.

## Test Boundary

Tests use intentionally varied, even semantically wrong, `answer_output` strings with a correct structured result to prove that text does not affect factual verification. Complementary tests use a polished natural-language answer with an incorrect structured result to prove that evidence, not prose, controls the outcome.

Provider and scripted-Pi validation in Task 11 must materialize this same trace shape. The semantic capability protocol introduced in Task 4 is the authoritative source for capability IDs, result schemas, and evidence references.
