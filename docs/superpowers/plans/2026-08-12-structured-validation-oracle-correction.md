# Structured Validation Oracle Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or execute inline task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Design reference:** [`2026-08-12-structured-validation-oracle-correction.md`](../specs/2026-08-12-structured-validation-oracle-correction.md)

**Goal:** Replace text-derived topology fact validation with structured tool-result and evidence validation, so entity recognition remains solely an LLM responsibility.

**Architecture:** The validation harness parses canonical successful tool-result events from a current-run trace. A structured oracle selects a required capability event, compares only explicitly declared typed result fields, and checks evidence references; it never reads `answer_output` to decide a simulator-backed fact. The final answer envelope remains a transport/readability contract, not a fact source.

**Tech Stack:** Python >=3.12, Pydantic >=2.12,<3, pytest >=9,<10, JSONL.

## Global Constraints

- The model, not the framework, resolves natural-language entities and chooses domain tools.
- Simulator-backed fact validation consumes only structured result events and current-run evidence references.
- `answer_output` is checked only as a strict non-empty answer envelope; it is never parsed for electrical entities, relationships, values, or units.
- A missing trace, matching result, or required evidence is a deterministic validation failure; no text fallback exists.
- Keep pandapower, pandas, NumPy, and SciPy out of `packages/grid-agent`.
- Keep command execution list-based with `shell=False` behavior.
- Do not change simulator protocol, Pi tool wiring, or provider execution in this correction.

---

## File Map

- Modify `packages/grid-agent/src/grid_agent/validation/cases.py`: declare the structured topology oracle arguments without text bus-name matching.
- Modify `packages/grid-agent/src/grid_agent/validation/oracles.py`: remove `branch_endpoints`; add `topology_branch_endpoints(event, arguments)` and recursive declared-field comparison.
- Modify `validation/run.py`: retain trace tool-call accounting and add canonical `ToolResultEvent` parsing plus structured-oracle/evidence failure classification.
- Modify `validation/suites/task-required/topology-line-endpoints-001.json`: state the expected typed branch/from-bus/to-bus result fields.
- Modify `packages/grid-agent/tests/validation/test_oracles.py`: remove natural-language endpoint cases and add structured-result tests.
- Modify `packages/grid-agent/tests/validation/test_run_harness.py`: emit canonical tool-result trace events and prove prose cannot affect topology validation.
- Modify `docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md`: replace the obsolete text-oracle implementation and Task 3 acceptance language with the structured contract.

### Task 1: Make structured tool results the only topology-fact oracle

**Files:**

- Modify `packages/grid-agent/src/grid_agent/validation/oracles.py`
- Modify `packages/grid-agent/src/grid_agent/validation/cases.py`
- Modify `validation/run.py`
- Modify `validation/suites/task-required/topology-line-endpoints-001.json`
- Modify `packages/grid-agent/tests/validation/test_oracles.py`
- Modify `packages/grid-agent/tests/validation/test_run_harness.py`

**Interfaces:**

- Consumes canonical JSONL event:

```json
{
  "event": "tool_result",
  "capability": "topology.branch.endpoints.get",
  "ok": true,
  "result": {
    "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    "from_bus": {"name": "6"},
    "to_bus": {"name": "11"}
  },
  "evidence_refs": ["evidence:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
}
```

- Produces `ToolResultEvent(capability: str, result: Mapping[str, JsonValue], evidence_refs: tuple[str, ...])`; `topology_branch_endpoints(event, arguments) -> bool`; and deterministic errors `verification_trace_missing`, `verification_result_missing`, `verification_evidence_missing`, and `structured_oracle_mismatch`.

- [ ] **Step 1: Replace text oracle tests with structured-result tests**

```python
def test_topology_oracle_matches_declared_result_fields() -> None:
    event = ToolResultEvent(
        capability="topology.branch.endpoints.get",
        result={
            "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
            "from_bus": {"name": "6", "asset_ref": "asset:bus:sha256:" + "a" * 64},
            "to_bus": {"name": "11", "asset_ref": "asset:bus:sha256:" + "b" * 64},
        },
        evidence_refs=("evidence:sha256:" + "c" * 64,),
    )
    expected = {
        "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
        "from_bus": {"name": "6"},
        "to_bus": {"name": "11"},
    }
    assert topology_branch_endpoints(event, expected) is True


def test_topology_oracle_rejects_wrong_structured_endpoint_even_when_prose_is_polished() -> None:
    event = ToolResultEvent(
        capability="topology.branch.endpoints.get",
        result={"from_bus": {"name": "6"}, "to_bus": {"name": "12"}},
        evidence_refs=("evidence:sha256:" + "d" * 64,),
    )
    assert topology_branch_endpoints(event, {"from_bus": {"name": "6"}, "to_bus": {"name": "11"}}) is False
```

Delete every `branch_endpoints` text-regex test, including line-number, language, punctuation, and unit cases.

- [ ] **Step 2: Verify the structured API is absent**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation/test_oracles.py -v
```

Expected: FAIL because `ToolResultEvent` and `topology_branch_endpoints` do not exist.

- [ ] **Step 3: Add the event model and declared-field matcher**

```python
# packages/grid-agent/src/grid_agent/validation/oracles.py
from dataclasses import dataclass
from collections.abc import Mapping
from pydantic import JsonValue


@dataclass(frozen=True)
class ToolResultEvent:
    capability: str
    result: Mapping[str, JsonValue]
    evidence_refs: tuple[str, ...]


def declared_fields_match(actual: JsonValue, expected: JsonValue) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and declared_fields_match(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def topology_branch_endpoints(event: ToolResultEvent, arguments: Mapping[str, JsonValue]) -> bool:
    return event.capability == "topology.branch.endpoints.get" and declared_fields_match(
        event.result, dict(arguments)
    )
```

Keep `contains_all` and `truthful_limitation` only for the explicitly informational cases; delete `branch_endpoints` and all regex helpers.

In `cases.py`, add the structured-case invariant directly to `ValidationCase`:

```python
from pydantic import model_validator


class ValidationCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    question: str = Field(min_length=1)
    suites: tuple[str, ...]
    model: str | None = None
    requirements: CaseRequirements
    oracle: OracleSpec

    @model_validator(mode="after")
    def require_one_capability_for_structured_oracle(self) -> "ValidationCase":
        if self.oracle.kind == "structured" and len(self.requirements.required_capabilities) != 1:
            raise ValueError("structured validation cases require exactly one capability")
        return self
```

- [ ] **Step 4: Change the topology case to declare facts, not prose tokens**

```json
"oracle": {
  "kind": "structured",
  "evaluator": "topology_branch_endpoints",
  "arguments": {
    "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
    "from_bus": {"name": "6"},
    "to_bus": {"name": "11"}
  }
}
```

Do not include `bus_names`, text patterns, line-display wording, or language requirements in this case.

- [ ] **Step 5: Parse canonical successful tool-result events in the harness**

Extend `TraceSummary` with `result_events: tuple[ToolResultEvent, ...]`. In `_load_trace`, retain current capability/tool-call extraction and additionally parse an event only when all conditions hold:

```python
event.get("event") == "tool_result"
and event.get("ok") is True
and isinstance(event.get("capability"), str)
and isinstance(event.get("result"), Mapping)
and isinstance(event.get("evidence_refs", []), list)
and all(isinstance(reference, str) for reference in event.get("evidence_refs", []))
```

Store `ToolResultEvent(event["capability"], event["result"], tuple(event.get("evidence_refs", [])))`. A malformed `tool_result` event appends `trace tool_result event is malformed at line <n>` and does not become a result candidate.

For `case.oracle.kind == "structured"`, implement this exact evaluation order:

```python
candidates = tuple(event for event in trace.result_events if event.capability == required_capability)
if not candidates:
    errors.append("verification_result_missing: " + required_capability)
elif case.requirements.requires_evidence and not any(event.evidence_refs for event in candidates):
    errors.append("verification_evidence_missing: " + required_capability)
elif not any(evaluator(event, case.oracle.arguments) for event in candidates):
    errors.append("structured_oracle_mismatch: " + case.oracle.evaluator)
```

If `trace is None` for a structured case, append `verification_trace_missing: <capability>` instead of parsing answer prose. The required capability is `case.requirements.required_capabilities[0]`; `ValidationCase` validation rejects a structured case with zero or more than one required capability.

- [ ] **Step 6: Add harness integration tests**

Add this local helper to `test_run_harness.py`; it writes a canonical trace and runs exactly the topology case:

```python
def _run_topology_case(tmp_path: Path, event: dict[str, object], answer_output: str) -> subprocess.CompletedProcess[str]:
    trace_path = tmp_path / "events.jsonl"
    trace_path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    cli = tmp_path / "fake_agent.py"
    cli.write_text(
        "import json, sys\n"
        f"print(json.dumps({{'question_id': sys.argv[1], 'answer_output': {answer_output!r}}}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable, str(RUNNER), "--cases-root", str(ROOT / "validation"),
            "--case-id", "topology-line-endpoints-001", "--trace-template", str(trace_path), "--",
            sys.executable, str(cli), "{case_id}",
        ],
        cwd=ROOT, text=True, capture_output=True, timeout=30,
    )


def _topology_event(*, to_bus: str = "11", evidence_refs: list[str] | None = None) -> dict[str, object]:
    return {
        "event": "tool_result", "capability": "topology.branch.endpoints.get", "ok": True,
        "result": {
            "branch": {"kind": "line", "namespace": "pandapower_index", "identifier": "11"},
            "from_bus": {"name": "6"}, "to_bus": {"name": to_bus},
        },
        "evidence_refs": evidence_refs if evidence_refs is not None else ["evidence:sha256:" + "a" * 64],
    }


def test_topology_validation_uses_structured_result_not_answer_wording(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(), "结论已生成。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 0
    assert records[0]["passed"] is True


def test_topology_validation_rejects_wrong_structured_result_not_prose(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(to_bus="12"), "线路11连接母线6与母线11。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["structured_oracle_mismatch: topology_branch_endpoints"]


def test_topology_validation_requires_matching_result_evidence(tmp_path: Path) -> None:
    completed = _run_topology_case(tmp_path, _topology_event(evidence_refs=[]), "结论已生成。")
    records = [json.loads(line) for line in completed.stdout.splitlines()]
    assert completed.returncode == 1
    assert records[0]["errors"] == ["verification_evidence_missing: topology.branch.endpoints.get"]
```

- [ ] **Step 7: Run focused validation and commit**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation -v
uv run --project packages/grid-agent python -m py_compile validation/run.py packages/grid-agent/src/grid_agent/validation/oracles.py packages/grid-agent/tests/validation/test_oracles.py packages/grid-agent/tests/validation/test_run_harness.py
git add validation packages/grid-agent/src/grid_agent/validation packages/grid-agent/tests/validation
git commit -m "fix(validation): verify structured topology facts"
```

Expected: text wording no longer changes topology-fact verdicts; a correct result plus evidence passes and a mismatched result fails deterministically.

### Task 2: Align the approved WP-A plan with structured-only validation

**Files:**

- Modify `docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md`
- Test `packages/grid-agent/tests/validation/test_case_contract.py`

**Interfaces:**

- Consumes the correction specification and Task 1 canonical trace contract.
- Produces a WP-A plan that has no text endpoint oracle, no text entity extraction, and a Task 11 scripted-Pi trace requirement that emits canonical tool-result events.

- [ ] **Step 1: Add a documentation-boundary assertion**

```python
def test_wp_a_plan_assigns_entities_to_the_model_and_facts_to_structured_results() -> None:
    plan = (ROOT / "docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md").read_text(encoding="utf-8")
    assert "topology_branch_endpoints" in plan
    assert "answer_output is never parsed for electrical entities" in plan
    assert "branch_endpoints(answer" not in plan
```

- [ ] **Step 2: Run it to establish the obsolete plan language**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation/test_case_contract.py::test_wp_a_plan_assigns_entities_to_the_model_and_facts_to_structured_results -v
```

Expected: FAIL because Task 3 still shows `branch_endpoints(answer, arguments)` and calls it a deterministic oracle.

- [ ] **Step 3: Replace the obsolete Task 3 plan sections**

Make these exact substitutions in the WP-A plan:

1. Replace `branch_endpoints` in the oracle registry/code block with `topology_branch_endpoints(event, arguments)`, and state it compares typed `branch`, `from_bus`, and `to_bus` fields from a successful `tool_result` trace event.
2. Replace the topology JSON example's `bus_names` text argument with the Task 1 declared result object.
3. Replace the harness description with canonical `tool_result` parsing, evidence-reference checking, and the four deterministic failure classes from the correction spec.
4. Add this literal sentence to Task 3: `answer_output is never parsed for electrical entities, relationships, values, or units.`
5. In Task 11 scripted-Pi requirements, require the fake Pi trace event to include the tool's typed result and `evidence_refs`, then assert those fields are the oracle input; remove any assertion that judges natural-language endpoint wording.

- [ ] **Step 4: Verify boundary test and validation suite**

```bash
uv run --project packages/grid-agent pytest packages/grid-agent/tests/validation -v
git diff --check
git add docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md packages/grid-agent/tests/validation/test_case_contract.py
git commit -m "docs: align WP-A validation with structured facts"
```

Expected: plan and tests describe one fact-verification boundary, with no framework-side entity recognition.

## Acceptance Gate

1. No validation code parses final-answer text to identify a simulator-backed entity, value, unit, or relationship.
2. The topology case passes with arbitrary non-empty answer prose only when its trace has the matching typed topology result and evidence reference.
3. The topology case fails when its typed result is incorrect even if prose states the desired answer.
4. Missing trace, matching result, and evidence each yield their named deterministic error.
5. Informational `contains_all` and `truthful_limitation` cases remain text-evaluated only because they have no simulator-backed fact claim.
6. The WP-A plan, correction spec, validation cases, and harness use the same canonical tool-result event contract.
