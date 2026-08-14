from __future__ import annotations

from grid_agent.analysis.capabilities import CapabilityContextSpec
from grid_agent.analysis.domain_projection import project_domain_result


CONTEXT_REF = "context:sha256:" + "1" * 64
REVISION_REF = "revision:sha256:" + "2" * 64
RESULT_REF = "result:sha256:" + "3" * 64
EVIDENCE_REF = "evidence:sha256:" + "4" * 64
CONSTRAINT_REF = "constraint:sha256:" + "5" * 64


def _spec(capability: str, projector: str, result_kind: str | None = None) -> CapabilityContextSpec:
    return CapabilityContextSpec(
        capability=capability,
        availability="published",
        requires_state=("model.active",),
        consumes_state=("model.active",),
        produces_state=("test.output",),
        invalidates_state=(),
        result_kind=result_kind,
        projector=projector,
    )


def test_model_constraint_projector_keeps_model_and_evidence_source() -> None:
    delta = project_domain_result(
        _spec("model.constraints.describe", "model-constraints-v1"),
        result={
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "constraints": [
                {
                    "constraint_ref": CONSTRAINT_REF,
                    "quantity": "bus.vm_pu",
                    "subject_kind": "bus",
                    "lower": 0.94,
                    "upper": 1.06,
                    "unit": "p.u.",
                    "applies_to_count": 39,
                    "source": {"kind": "model", "table": "bus", "fields": ["min_vm_pu", "max_vm_pu"]},
                }
            ],
            "evidence_refs": [EVIDENCE_REF],
        },
        arguments={"context_ref": CONTEXT_REF},
        turn_id="analysis-test-t002",
        result_paths={},
        active_revision_ref=REVISION_REF,
    )

    constraint = delta.constraints[0]
    assert constraint.lower == 0.94
    assert constraint.upper == 1.06
    assert constraint.source_kind == "model"
    assert constraint.source_ref == EVIDENCE_REF
    assert constraint.producer_turn_id == "analysis-test-t002"


def test_powerflow_projector_registers_applicable_calculation() -> None:
    delta = project_domain_result(
        _spec("analysis.powerflow.ac.run", "powerflow-ac-v1", "powerflow.ac"),
        result={
            "result_ref": RESULT_REF,
            "context_ref": CONTEXT_REF,
            "revision_ref": REVISION_REF,
            "converged": True,
            "solver": {"algorithm": "nr"},
            "total_active_loss": {"value": 1.2, "unit": "MW"},
            "evidence_refs": [EVIDENCE_REF],
        },
        arguments={"context_ref": CONTEXT_REF},
        turn_id="analysis-test-t003",
        result_paths={RESULT_REF: "evidence/results/powerflow.json"},
        active_revision_ref=REVISION_REF,
    )

    calculation = delta.calculations[0]
    assert calculation.result_ref == RESULT_REF
    assert calculation.kind == "powerflow.ac"
    assert calculation.status == "converged"
    assert calculation.summary["total_active_loss"] == {"value": 1.2, "unit": "MW"}
    assert calculation.artifact_path == "evidence/results/powerflow.json"
