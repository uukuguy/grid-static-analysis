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
    state = context_with_baseline()

    with pytest.raises(ContextTransitionError, match="verified facts must come from simulator evidence"):
        reduce_context(
            state,
            ContextEventDraft(
                event_type="fact.verified",
                turn_id="analysis-test-t001",
                payload={
                    "fact_ref": "fact:sha256:" + "5" * 64,
                    "statement": "model-authored fact",
                    "evidence_refs": [EVIDENCE_REF],
                    "authored_by": "model",
                },
            ),
        )
