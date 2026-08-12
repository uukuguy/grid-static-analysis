from pathlib import Path

from grid_agent.validation.cases import load_cases


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
