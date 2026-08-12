from pathlib import Path

import pytest

from grid_agent.validation.cases import ValidationCase, load_cases


ROOT = Path(__file__).resolve().parents[4]


def test_validation_cases_have_unique_ids_and_deterministic_oracles() -> None:
    cases = load_cases(ROOT / "validation")

    assert len(cases) == 3
    assert len({case.id for case in cases}) == len(cases)
    assert all(case.oracle.kind in {"structured", "knowledge", "limitation"} for case in cases)


def test_topology_case_forbids_unnecessary_powerflow() -> None:
    case = next(item for item in load_cases(ROOT / "validation") if item.id == "topology-line-endpoints-001")

    assert case.requirements.required_capabilities == ("topology.branch.endpoints.get",)
    assert case.requirements.forbidden_capabilities == ("analysis.powerflow.ac.run",)
    assert case.requirements.max_tool_calls == 4
    assert case.requirements.requires_evidence is True


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
