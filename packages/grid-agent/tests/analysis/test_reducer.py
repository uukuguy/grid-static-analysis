import pytest

from grid_agent.analysis.models import ContextEventDraft
from grid_agent.analysis.reducer import (
    ContextTransitionError,
    canonical_state_hash,
    initial_context,
    reduce_context,
)


CONTEXT_REF = "context:sha256:" + "1" * 64
REVISION_REF = "revision:sha256:" + "2" * 64
RESULT_REF = "result:sha256:" + "3" * 64
EVIDENCE_REF = "evidence:sha256:" + "4" * 64
SECOND_CONTEXT_REF = "context:sha256:" + "5" * 64
SECOND_REVISION_REF = "revision:sha256:" + "6" * 64

BASELINE = {
    "context_ref": CONTEXT_REF,
    "revision_ref": REVISION_REF,
    "path": "evidence/contexts/context.json",
    "source": {
        "capability": "context.open",
        "grid_capability_protocol": "1.0",
        "pandapower_version": "3.4.0",
    },
    "network": {
        "name": "case-test",
        "bus_count": 3,
        "line_count": 2,
        "trafo_count": 0,
    },
}

RESULT = {
    "result_ref": RESULT_REF,
    "revision_ref": REVISION_REF,
    "path": "evidence/results/powerflow.json",
    "evidence_refs": [EVIDENCE_REF],
    "solver_summary": {
        "success": True,
        "algorithm": "nr",
        "iterations": 3,
        "total_loss_mw": 0.125,
    },
    "producer_observation": {
        "capability": "analysis.powerflow.ac.run",
        "grid_capability_protocol": "1.0",
        "pandapower_version": "3.4.0",
    },
}

RANKING_OBSERVATION = {
    "observation_ref": "observation-2",
    "path": "tool-results/002/ranking.json",
    "produced_refs": [],
    "summary": {
        "ranked_by": "loading_percent",
        "top_ref": RESULT_REF,
    },
    "producer_observation": {
        "capability": "result.branches.rank",
        "grid_capability_protocol": "1.0",
        "pandapower_version": "3.4.0",
    },
}


EVIDENCE = {
    "evidence_ref": EVIDENCE_REF,
    "path": "evidence/network-facts/powerflow-fact.json",
    "kind": "simulator",
    "refs": [RESULT_REF],
    "summary": {
        "provenance": "gridctl",
        "description": "deterministic simulator evidence",
    },
}


def context_with_baseline():
    state = initial_context(
        analysis_id="analysis-test",
        input_payload={
            "copied_path": "input/instructions.md.txt",
            "source_path": "task.txt",
            "sha256": "a" * 64,
            "instruction_count": 2,
        },
        runtime_payload={
            "provider": "test",
            "model": "scripted",
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        },
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.started",
            turn_id="analysis-test-t001",
            payload={
                "ordinal": 1,
                "instruction": "运行潮流",
                "instruction_sha256": "b" * 64,
                "nonce_sha256": "c" * 64,
            },
        ),
    )
    return reduce_context(
        state,
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id="analysis-test-t001",
            capability="context.open",
            payload=BASELINE,
        ),
    )


def context_with_completed_turn():
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    return reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.completed",
            turn_id="analysis-test-t001",
            payload={
                "status": "success",
                "answer_path": "turns/001/answer.json",
                "answer_sha256": "d" * 64,
                "duration_seconds": 1.5,
                "consumed_refs": [],
                "produced_refs": [RESULT_REF],
            },
        ),
    )


def context_with_simulator_evidence():
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    return reduce_context(
        state,
        ContextEventDraft(
            event_type="evidence.registered",
            turn_id="analysis-test-t001",
            capability="gridctl.evidence.register",
            payload=EVIDENCE,
        ),
    )


def test_domain_projection_tracks_active_model_and_result_applicability() -> None:
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="domain.state.projected",
            turn_id="analysis-test-t001",
            capability="context.open",
            payload={
                "projector": "model-context-v1",
                "model": {
                    "context_ref": CONTEXT_REF,
                    "revision_ref": REVISION_REF,
                    "model_id": "ieee39",
                    "source": "pandapower.networks.case39",
                    "counts": {"buses": 39, "lines": 35, "transformers": 11},
                },
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="domain.state.projected",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload={
                "projector": "powerflow-ac-v1",
                "calculations": [
                    {
                        "result_ref": RESULT_REF,
                        "kind": "powerflow.ac",
                        "context_ref": CONTEXT_REF,
                        "revision_ref": REVISION_REF,
                        "status": "converged",
                        "solver": {"algorithm": "nr"},
                        "summary": {"total_active_loss_mw": 0.125},
                        "artifact_path": RESULT["path"],
                        "evidence_refs": [EVIDENCE_REF],
                        "producer_capability": "analysis.powerflow.ac.run",
                        "producer_turn_id": "analysis-test-t001",
                    }
                ],
            },
        ),
    )

    assert state.domain_state.model is not None
    assert state.domain_state.model.model_id == "ieee39"
    assert state.domain_state.calculations[RESULT_REF].revision_ref == REVISION_REF


def test_domain_projection_rejects_calculation_for_different_revision() -> None:
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )

    with pytest.raises(ContextTransitionError, match="calculation revision"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="domain.state.projected",
                turn_id="analysis-test-t001",
                capability="analysis.powerflow.ac.run",
                payload={
                    "projector": "powerflow-ac-v1",
                    "calculations": [
                        {
                            "result_ref": RESULT_REF,
                            "kind": "powerflow.ac",
                            "context_ref": CONTEXT_REF,
                            "revision_ref": SECOND_REVISION_REF,
                            "status": "converged",
                            "artifact_path": RESULT["path"],
                            "producer_capability": "analysis.powerflow.ac.run",
                            "producer_turn_id": "analysis-test-t001",
                        }
                    ],
                },
            ),
        )


def test_new_active_model_preserves_historical_calculations() -> None:
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="domain.state.projected",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload={
                "projector": "powerflow-ac-v1",
                "calculations": [
                    {
                        "result_ref": RESULT_REF,
                        "kind": "powerflow.ac",
                        "context_ref": CONTEXT_REF,
                        "revision_ref": REVISION_REF,
                        "status": "converged",
                        "artifact_path": RESULT["path"],
                        "producer_capability": "analysis.powerflow.ac.run",
                        "producer_turn_id": "analysis-test-t001",
                    }
                ],
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id="analysis-test-t001",
            capability="context.open",
            payload={
                **BASELINE,
                "context_ref": SECOND_CONTEXT_REF,
                "revision_ref": SECOND_REVISION_REF,
                "path": "evidence/contexts/second.json",
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="domain.state.projected",
            turn_id="analysis-test-t001",
            capability="context.open",
            payload={
                "projector": "model-context-v1",
                "model": {
                    "context_ref": SECOND_CONTEXT_REF,
                    "revision_ref": SECOND_REVISION_REF,
                    "model_id": "second-model",
                    "source": "registered.second",
                },
            },
        ),
    )

    assert state.domain_state.model is not None
    assert state.domain_state.model.context_ref == SECOND_CONTEXT_REF
    assert RESULT_REF in state.domain_state.calculations


def test_context_reducer_registers_baseline_result_and_cross_turn_consumption() -> None:
    state = initial_context(
        analysis_id="analysis-test",
        input_payload={
            "copied_path": "input/instructions.md.txt",
            "source_path": "task.txt",
            "sha256": "a" * 64,
            "instruction_count": 2,
        },
        runtime_payload={
            "provider": "test",
            "model": "scripted",
            "grid_capability_protocol": "1.0",
            "pandapower_version": "3.4.0",
        },
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.started",
            turn_id="analysis-test-t001",
            payload={
                "ordinal": 1,
                "instruction": "运行潮流",
                "instruction_sha256": "b" * 64,
                "nonce_sha256": "c" * 64,
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="simulator.context.opened",
            turn_id="analysis-test-t001",
            capability="context.open",
            payload=BASELINE,
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.completed",
            turn_id="analysis-test-t001",
            payload={
                "status": "success",
                "answer_path": "turns/001/answer.json",
                "answer_sha256": "d" * 64,
                "duration_seconds": 1.5,
                "consumed_refs": [],
                "produced_refs": [RESULT_REF],
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.started",
            turn_id="analysis-test-t002",
            payload={
                "ordinal": 2,
                "instruction": "排序",
                "instruction_sha256": "e" * 64,
                "nonce_sha256": "f" * 64,
            },
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="tool.observation.recorded",
            turn_id="analysis-test-t002",
            capability="result.branches.rank",
            payload={**RANKING_OBSERVATION, "consumed_refs": [RESULT_REF]},
        ),
    )

    assert state.active_context_ref == CONTEXT_REF
    assert state.results[RESULT_REF].revision_ref == REVISION_REF
    assert state.current_turn.consumed_refs == [RESULT_REF]
    assert state.observations["observation-2"].produced_refs == []
    assert canonical_state_hash(state) == canonical_state_hash(state.model_copy(deep=True))


def test_context_reducer_rejects_result_from_mismatched_revision() -> None:
    state = context_with_baseline()
    bad = ContextEventDraft(
        event_type="result.registered",
        turn_id="analysis-test-t001",
        capability="analysis.powerflow.ac.run",
        payload={**RESULT, "revision_ref": "revision:sha256:" + "9" * 64},
    )
    with pytest.raises(ContextTransitionError, match="does not match registered baseline"):
        reduce_context(state, bad)


def test_context_reducer_rejects_duplicate_active_turn() -> None:
    state = context_with_baseline()

    with pytest.raises(ContextTransitionError, match="active turn already exists"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="turn.started",
                turn_id="analysis-test-t002",
                payload={
                    "ordinal": 2,
                    "instruction": "排序",
                    "instruction_sha256": "e" * 64,
                    "nonce_sha256": "f" * 64,
                },
            ),
        )


def test_context_reducer_rejects_model_authored_verified_fact() -> None:
    state = context_with_simulator_evidence()

    with pytest.raises(ContextTransitionError, match="explicit simulator/gridctl provenance"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="fact.verified",
                turn_id="analysis-test-t001",
                capability="gridctl.fact.verify",
                payload={
                    "fact_ref": "fact:sha256:" + "5" * 64,
                    "statement": "model-authored fact",
                    "evidence_refs": [EVIDENCE_REF],
                    "authored_by": "model",
                },
            ),
        )


def test_context_reducer_rejects_verified_fact_without_explicit_simulator_provenance() -> None:
    state = context_with_simulator_evidence()

    with pytest.raises(ContextTransitionError, match="explicit simulator/gridctl provenance"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="fact.verified",
                turn_id="analysis-test-t001",
                capability="gridctl.fact.verify",
                payload={
                    "fact_ref": "fact:sha256:" + "5" * 64,
                    "statement": "omitted provenance",
                    "evidence_refs": [EVIDENCE_REF],
                },
            ),
        )


def test_context_reducer_rejects_verified_fact_without_simulator_evidence_provenance() -> None:
    state = context_with_baseline()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="result.registered",
            turn_id="analysis-test-t001",
            capability="analysis.powerflow.ac.run",
            payload=RESULT,
        ),
    )
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="evidence.registered",
            turn_id="analysis-test-t001",
            capability="manual.evidence.register",
            payload={**EVIDENCE, "kind": "manual", "summary": {"provenance": "model"}},
        ),
    )

    with pytest.raises(ContextTransitionError, match="evidence provenance is not simulator/gridctl"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="fact.verified",
                turn_id="analysis-test-t001",
                capability="gridctl.fact.verify",
                payload={
                    "fact_ref": "fact:sha256:" + "5" * 64,
                    "statement": "unsupported evidence provenance",
                    "evidence_refs": [EVIDENCE_REF],
                    "authored_by": "gridctl",
                },
            ),
        )


def test_context_reducer_rejects_ranking_observation_that_produces_refs() -> None:
    state = context_with_completed_turn()
    state = reduce_context(
        state,
        ContextEventDraft(
            event_type="turn.started",
            turn_id="analysis-test-t002",
            payload={
                "ordinal": 2,
                "instruction": "排序",
                "instruction_sha256": "e" * 64,
                "nonce_sha256": "f" * 64,
            },
        ),
    )

    with pytest.raises(ContextTransitionError, match="result.branches.rank observations must not produce refs"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="tool.observation.recorded",
                turn_id="analysis-test-t002",
                capability="result.branches.rank",
                payload={**RANKING_OBSERVATION, "produced_refs": ["observation:sha256:" + "6" * 64], "consumed_refs": [RESULT_REF]},
            ),
        )


def test_context_reducer_rejects_ranking_observation_without_preexisting_result_ref() -> None:
    state = context_with_baseline()

    with pytest.raises(ContextTransitionError, match="result.branches.rank must consume a preexisting result ref"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="tool.observation.recorded",
                turn_id="analysis-test-t001",
                capability="result.branches.rank",
                payload={**RANKING_OBSERVATION, "consumed_refs": []},
            ),
        )


def test_context_reducer_rejects_normal_mutations_after_terminal_status() -> None:
    state = reduce_context(context_with_completed_turn(), ContextEventDraft(event_type="analysis.completed"))

    terminal_mutations = [
        ContextEventDraft(event_type="analysis.started"),
        ContextEventDraft(
            event_type="turn.started",
            turn_id="analysis-test-t002",
            payload={
                "ordinal": 2,
                "instruction": "排序",
                "instruction_sha256": "e" * 64,
                "nonce_sha256": "f" * 64,
            },
        ),
        ContextEventDraft(
            event_type="audit.diagnostic.recorded",
            payload={"message": "late diagnostic"},
        ),
    ]
    for draft in terminal_mutations:
        with pytest.raises(ContextTransitionError, match="terminal analysis context cannot be mutated"):
            reduce_context(state, draft)


def test_context_reducer_rejects_duplicate_completed_turn_id() -> None:
    state = context_with_completed_turn()

    with pytest.raises(ContextTransitionError, match="turn_id was already completed"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="turn.started",
                turn_id="analysis-test-t001",
                payload={
                    "ordinal": 2,
                    "instruction": "重复",
                    "instruction_sha256": "e" * 64,
                    "nonce_sha256": "f" * 64,
                },
            ),
        )
