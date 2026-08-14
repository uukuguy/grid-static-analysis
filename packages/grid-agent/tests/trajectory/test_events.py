from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from grid_agent.trajectory.canonical import canonical_json_bytes, sha256_ref
from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventDraft,
    EventRefs,
    EventSource,
    RunEvent,
    RunScope,
    build_event,
)


def test_build_event_is_canonical_and_hash_stable() -> None:
    draft = EventDraft(
        event_type="turn.started",
        scope=RunScope(turn_id="analysis-test-t001"),
        payload={"ordinal": 1, "instruction_sha256": "a" * 64},
    )
    event = build_event(
        draft,
        analysis_id="analysis-test",
        sequence=1,
        timestamp=datetime(2026, 8, 14, tzinfo=UTC),
        previous_event_hash="sha256:" + "0" * 64,
    )

    round_trip = RunEvent.model_validate_json(canonical_json_bytes(event.model_dump(mode="json")))

    assert round_trip == event
    assert event.schema_version == "grid-run-event/1.0"
    assert event.timestamp == "2026-08-14T00:00:00.000000Z"
    assert event.event_hash.startswith("sha256:")
    assert len(event.event_hash) == 71


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"step_id": "analysis-test-t001-s001"}, "step_id requires turn_id"),
        (
            {"turn_id": "analysis-test-t001", "request_id": "request-1"},
            "request_id requires step_id",
        ),
        (
            {
                "turn_id": "analysis-test-t001",
                "step_id": "analysis-test-t001-s001",
                "tool_call_id": "call_1",
            },
            "tool_call_id requires request_id",
        ),
    ],
)
def test_scope_rejects_missing_parent(kwargs: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        RunScope(**kwargs)


def test_event_payload_is_closed_for_its_type() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        EventDraft(
            event_type="analysis.completed",
            payload={"completed_turns": 9, "total_turns": 9, "unexpected": True},
        )


def test_event_payload_is_normalized_through_its_model() -> None:
    draft = EventDraft(
        event_type="business.claim.declared",
        payload={
            "submission_id": "submission-1",
            "statement": "The simulated feeder has a thermal constraint.",
            "category": "constraint",
        },
    )

    assert draft.payload == {
        "submission_id": "submission-1",
        "statement": "The simulated feeder has a thermal constraint.",
        "category": "constraint",
        "result_refs": [],
        "evidence_refs": [],
    }


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json_bytes({"value": float("nan")})


def test_canonical_json_sorts_keys_preserves_list_order_and_ends_with_newline() -> None:
    value = {"z": [2, 1], "a": "电网"}

    assert canonical_json_bytes(value) == b'{"a":"\xe7\x94\xb5\xe7\xbd\x91","z":[2,1]}\n'
    assert sha256_ref(b"value") == "sha256:" + "cd42404d52ad55ccfa9aca4adc828aa5800ad9d385a0671fbcbf724118320619"


def test_envelope_models_reject_invalid_source_context_and_refs() -> None:
    with pytest.raises(ValidationError):
        EventSource(kind="derived", producer="projector", integrity="verified")
    with pytest.raises(ValidationError):
        Causation(parent_sequence=0)
    with pytest.raises(ValidationError):
        ContextBoundary(before_revision=-1)
    with pytest.raises(ValidationError):
        EventRefs(consumed=("",))


def test_build_event_uses_utc_and_rejects_invalid_hashes() -> None:
    draft = EventDraft(event_type="analysis.started", payload={})

    event = build_event(
        draft,
        analysis_id="analysis-test",
        sequence=1,
        timestamp=datetime(2026, 8, 14, 8, tzinfo=UTC),
        previous_event_hash="sha256:" + "0" * 64,
    )

    assert event.timestamp == "2026-08-14T08:00:00.000000Z"
    with pytest.raises(ValidationError):
        build_event(
            draft,
            analysis_id="analysis-test",
            sequence=1,
            timestamp=datetime(2026, 8, 14, tzinfo=UTC),
            previous_event_hash="not-a-hash",
        )


def test_build_event_rejects_naive_timestamp() -> None:
    draft = EventDraft(event_type="analysis.started", payload={})

    with pytest.raises(ValueError, match="aware instant"):
        build_event(
            draft,
            analysis_id="analysis-test",
            sequence=1,
            timestamp=datetime(2026, 8, 14),
            previous_event_hash="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-02-30T00:00:00.000000Z",
        "2026-01-01T24:00:00.000000Z",
    ],
)
def test_run_event_rejects_semantically_invalid_canonical_timestamp(
    timestamp: str,
) -> None:
    with pytest.raises(ValidationError, match="valid UTC timestamp"):
        RunEvent(
            event_type="analysis.started",
            payload={},
            analysis_id="analysis-test",
            sequence=1,
            timestamp=timestamp,
            previous_event_hash="sha256:" + "0" * 64,
            event_hash="sha256:" + "a" * 64,
        )


@pytest.mark.parametrize(
    ("sequence", "previous_event_hash", "message"),
    [
        (
            1,
            "sha256:" + "a" * 64,
            "sequence 1 requires the zero predecessor seed",
        ),
        (
            2,
            "sha256:" + "0" * 64,
            "zero predecessor seed is only valid for sequence 1",
        ),
    ],
)
def test_run_event_enforces_zero_predecessor_seed_boundaries(
    sequence: int,
    previous_event_hash: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        RunEvent(
            event_type="analysis.started",
            payload={},
            analysis_id="analysis-test",
            sequence=sequence,
            timestamp="2026-08-14T00:00:00.000000Z",
            previous_event_hash=previous_event_hash,
            event_hash="sha256:" + "a" * 64,
        )
