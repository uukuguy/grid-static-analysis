from pathlib import Path

import pytest

from grid_agent.validation.cases import ValidationCase, load_cases


ROOT = Path(__file__).resolve().parents[4]


def test_validation_cases_have_unique_ids_and_deterministic_oracles() -> None:
    cases = load_cases(ROOT / "validation")

    assert len({case.id for case in cases}) == len(cases)
    assert all(case.oracle.kind in {"structured", "knowledge", "limitation"} for case in cases)


def test_task11_validation_inventory_covers_wp_a_required_cases() -> None:
    cases = load_cases(ROOT / "validation")
    by_id = {case.id: case for case in cases}

    task_required = {
        "topology-line-endpoints-001",
        "knowledge-n1-violation-types-001",
        "knowledge-ac-tool-inputs-001",
        "analysis-ac-loss-001",
        "analysis-top-five-line-loading-001",
        "limitation-line-171-n1-001",
        "analysis-critical-line-outage-ordering-001",
        "limitation-voltage-overload-risk-001",
    }
    static_core = {
        "static-line-lookup-by-alias-001",
        "static-bus-listing-001",
        "static-branch-dataset-schema-001",
        "static-components-001",
        "static-invalid-field-recovery-001",
        "static-ac-non-convergence-001",
        "static-n1-partial-failure-001",
        "static-stale-result-ref-001",
        "static-evidence-mismatch-001",
    }

    assert task_required <= set(by_id)
    assert static_core <= set(by_id)
    assert all("task-required" in by_id[case_id].suites for case_id in task_required)
    assert all("static-analysis-core" in by_id[case_id].suites for case_id in static_core)
    assert all(by_id[case_id].oracle.evaluator != "contains_all" for case_id in task_required if "analysis-" in case_id)
    assert all(by_id[case_id].oracle.kind == "limitation" for case_id in {
        "limitation-line-171-n1-001",
        "limitation-voltage-overload-risk-001",
    })
    assert all(
        "policy" not in case.oracle.arguments
        for case in cases
    )


def test_topology_case_forbids_unnecessary_powerflow() -> None:
    case = next(item for item in load_cases(ROOT / "validation") if item.id == "topology-line-endpoints-001")

    assert case.requirements.required_capabilities == ("topology.branch.endpoints.get",)
    assert case.requirements.forbidden_capabilities == ("analysis.powerflow.ac.run",)
    assert case.requirements.max_tool_calls == 4
    assert case.requirements.requires_evidence is True


def test_wp_a_plan_assigns_entities_to_the_model_and_facts_to_structured_results() -> None:
    plan = (
        ROOT / "docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md"
    ).read_text(encoding="utf-8")

    assert "topology_branch_endpoints" in plan
    assert "answer_output is never parsed for electrical entities" in plan
    assert "branch_endpoints(answer" not in plan


def test_structured_validation_case_requires_exactly_one_capability() -> None:
    payload = {
        "id": "invalid-structured-capabilities",
        "question": "Which buses does line 11 connect?",
        "suites": ["task-required"],
        "requirements": {
            "required_capabilities": ["topology.branch.endpoints.get", "analysis.powerflow.ac.run"],
            "forbidden_capabilities": [],
            "max_tool_calls": 4,
            "requires_evidence": True,
        },
        "oracle": {
            "kind": "structured",
            "evaluator": "topology_branch_endpoints",
            "arguments": {"from_bus": {"name": "6"}, "to_bus": {"name": "11"}},
        },
    }

    with pytest.raises(ValueError, match="structured validation cases require exactly one capability"):
        ValidationCase.model_validate(payload)
