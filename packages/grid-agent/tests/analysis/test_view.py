from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_agent.analysis.models import (
    AnalysisContext,
    BaselineRecord,
    EvidenceRecord,
    InputRecord,
    LimitationRecord,
    ResultRecord,
    RuntimeRecord,
    TurnRecord,
    VerifiedFact,
)
from grid_agent.analysis.view import ContextViewTooLarge, build_context_view, materialize_context_view


CONTEXT_REF = "context:sha256:" + "1" * 64
REVISION_REF = "revision:sha256:" + "2" * 64
RESULT_REF = "result:sha256:" + "3" * 64
EVIDENCE_REF = "evidence:sha256:" + "4" * 64


def test_context_view_is_bounded_and_keeps_reusable_provenance(context_with_large_results: AnalysisContext) -> None:
    view = build_context_view(context_with_large_results)

    encoded = json.dumps(view, ensure_ascii=False)

    assert view["schema_version"] == "analysis-context-view/1.0"
    assert view["revision"] == context_with_large_results.revision
    assert view["state_hash"] == context_with_large_results.state_hash
    assert view["active_baseline"] == {
        "context_ref": CONTEXT_REF,
        "revision_ref": REVISION_REF,
        "network": {"model_id": "ieee39", "counts": {"bus": 39, "line": 35}},
    }
    assert view["completed_turns"] == [
        {
            "turn_id": "analysis-test-t001",
            "ordinal": 1,
            "status": "success",
            "answer_path": "turns/001/answer.json",
            "consumed_refs": [],
            "produced_refs": [RESULT_REF],
        }
    ]
    assert view["reusable_results"][0]["result_ref"] == RESULT_REF
    assert view["reusable_results"][0]["evidence_refs"] == [EVIDENCE_REF]
    assert view["verified_facts"]["branch.loading_percent"][0]["value"] == 91.2
    assert "branch_results" not in encoded
    assert len(encoded.encode("utf-8")) < 64_000


def test_context_view_caps_facts_per_predicate_deterministically(context_with_large_results: AnalysisContext) -> None:
    view = build_context_view(context_with_large_results)

    facts = view["verified_facts"]["branch.loading_percent"]

    assert len(facts) == 20
    assert [fact["fact_ref"] for fact in facts] == sorted(fact["fact_ref"] for fact in facts)


def test_materialize_context_view_writes_canonical_json(tmp_path: Path, context_with_large_results: AnalysisContext) -> None:
    path = tmp_path / "context" / "analysis-context-view.json"

    materialize_context_view(context_with_large_results, path)

    assert json.loads(path.read_text(encoding="utf-8")) == build_context_view(context_with_large_results)
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_context_view_raises_instead_of_truncating_provenance(context_with_large_results: AnalysisContext) -> None:
    oversize_facts = {
        f"fact:sha256:{index:064x}": VerifiedFact(
            fact_ref=f"fact:sha256:{index:064x}",
            statement=json.dumps(
                {
                    "predicate": "oversized.text",
                    "value": "x" * 4_000,
                    "context_ref": CONTEXT_REF,
                    "revision_ref": REVISION_REF,
                }
            ),
            evidence_refs=[EVIDENCE_REF],
            verifier_capability="analysis.powerflow.ac.run",
        )
        for index in range(20)
    }
    context = context_with_large_results.model_copy(update={"verified_facts": oversize_facts})

    with pytest.raises(ContextViewTooLarge):
        build_context_view(context)


@pytest.fixture
def context_with_large_results() -> AnalysisContext:
    large_branch_results = [
        {"branch_ref": f"asset:line:{index}", "loading_percent": 50.0 + index}
        for index in range(5_000)
    ]
    facts = {
        f"fact:sha256:{index:064x}": VerifiedFact(
            fact_ref=f"fact:sha256:{index:064x}",
            statement=json.dumps(
                {
                    "predicate": "branch.loading_percent",
                    "branch_ref": f"asset:line:{index}",
                    "value": 91.2 + index,
                    "unit": "%",
                    "context_ref": CONTEXT_REF,
                    "revision_ref": REVISION_REF,
                    "branch_results": large_branch_results,
                },
                sort_keys=True,
            ),
            evidence_refs=[EVIDENCE_REF],
            verifier_capability="result.branches.rank",
        )
        for index in range(25)
    }
    return AnalysisContext(
        analysis_id="analysis-test",
        revision=9,
        state_hash="sha256:test",
        status="running",
        input=InputRecord(
            copied_path="input/instructions.md.txt",
            source_path="task.md.txt",
            sha256="a" * 64,
            instruction_count=2,
        ),
        runtime=RuntimeRecord(
            provider="test",
            model="scripted",
            grid_capability_protocol="1.0",
            pandapower_version="3.4.0",
        ),
        baselines={
            CONTEXT_REF: BaselineRecord(
                context_ref=CONTEXT_REF,
                revision_ref=REVISION_REF,
                path="evidence/contexts/baseline.json",
                source={"model_id": "ieee39", "source": "registered"},
                network={"model_id": "ieee39", "counts": {"bus": 39, "line": 35}},
            )
        },
        active_context_ref=CONTEXT_REF,
        turns=[
            TurnRecord(
                turn_id="analysis-test-t001",
                ordinal=1,
                instruction="run powerflow",
                instruction_sha256="b" * 64,
                nonce_sha256="c" * 64,
                status="success",
                answer_path="turns/001/answer.json",
                answer_sha256="d" * 64,
                consumed_refs=[],
                produced_refs=[RESULT_REF],
            )
        ],
        results={
            RESULT_REF: ResultRecord(
                result_ref=RESULT_REF,
                turn_id="analysis-test-t001",
                capability="analysis.powerflow.ac.run",
                revision_ref=REVISION_REF,
                path="evidence/results/powerflow.json",
                evidence_refs=[EVIDENCE_REF],
                solver_summary={
                    "converged": True,
                    "total_active_loss": 1.25,
                    "branch_results": large_branch_results,
                },
                producer_observation={
                    "tool_name": "grid_analysis_powerflow_ac",
                    "args": {"context_ref": CONTEXT_REF},
                    "observation_ref": "observation:sha256:" + "5" * 64,
                    "branch_results": large_branch_results,
                },
            )
        },
        evidence={
            EVIDENCE_REF: EvidenceRecord(
                evidence_ref=EVIDENCE_REF,
                turn_id="analysis-test-t001",
                capability="analysis.powerflow.ac.run",
                path="evidence/analysis/powerflow-evidence.json",
                kind="analysis",
                refs=[RESULT_REF],
                summary={"kind": "powerflow"},
            )
        },
        verified_facts=facts,
        unresolved_limitations=[
            LimitationRecord(
                limitation_ref="limitation:analysis-test",
                turn_id="analysis-test-t001",
                message="one branch outage did not converge",
                refs=[RESULT_REF],
            )
        ],
    )
