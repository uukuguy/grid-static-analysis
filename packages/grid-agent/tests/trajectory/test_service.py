from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from grid_agent.trajectory.events import EventSource, RunScope
from grid_agent.trajectory.projection_models import (
    ArtifactIndex,
    ArtifactIndexRecord,
    BusinessNode,
    ContextCheckpoint,
    ContextFrame,
    ProjectionDiagnostic,
)
from grid_agent.trajectory.replay import ImportedRunEvent, SourceCoordinate


def test_imported_event_keeps_null_time_and_importer_integrity_label() -> None:
    event = ImportedRunEvent(
        analysis_id="analysis-old",
        sequence=1,
        timestamp=None,
        event_type="turn.started",
        import_previous_hash="sha256:" + "0" * 64,
        import_hash="sha256:" + "1" * 64,
        source_coordinate=SourceCoordinate(
            path="context/context-events.jsonl", sequence=2, sha256="a" * 64
        ),
        scope=RunScope(turn_id="analysis-old-t001"),
        source=EventSource(
            kind="observed",
            producer="legacy-v0.2-importer",
            integrity="importer-integrity",
        ),
        payload={"ordinal": 1, "instruction_sha256": "b" * 64},
    )

    assert event.schema_version == "grid-run-import-event/1.0"
    assert event.timestamp is None
    assert event.source.integrity == "importer-integrity"


def test_imported_event_rejects_native_integrity_claim() -> None:
    with pytest.raises(ValidationError, match="importer-integrity"):
        ImportedRunEvent(
            analysis_id="analysis-old",
            sequence=1,
            timestamp=None,
            event_type="turn.started",
            import_previous_hash="sha256:" + "0" * 64,
            import_hash="sha256:" + "1" * 64,
            source_coordinate=SourceCoordinate(
                path="context/context-events.jsonl", sequence=2, sha256="a" * 64
            ),
            source=EventSource(kind="observed", integrity="verified"),
        )


def test_projection_nodes_require_provenance_for_derived_source() -> None:
    with pytest.raises(ValidationError, match="derived node requires"):
        BusinessNode(
            id="node-1",
            source="derived",
            source_sequences=(),
            rule_id=None,
            status="completed",
            kind="context-change",
            title="Changed",
        )


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (
            ContextFrame,
            {
                "id": "context-1",
                "source_sequences": (1,),
                "source_sequence": 1,
                "before_revision": 0,
                "after_revision": 1,
                "before_state_hash": "sha256:" + "a" * 64,
                "after_state_hash": "sha256:" + "b" * 64,
                "before_state": {},
                "delta": {},
                "after_state": {},
                "request_artifact_ref": "artifact:request",
            },
        ),
        (
            ProjectionDiagnostic,
            {
                "id": "diagnostic-1",
                "source_sequences": (1,),
                "severity": "warning",
                "code": "missing",
                "message": "Unavailable",
            },
        ),
    ],
)
def test_default_derived_projection_nodes_require_nonempty_rule_id(
    model: type[object], kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="rule_id"):
        model(**kwargs)  # type: ignore[operator]

    with pytest.raises(ValidationError, match="rule_id"):
        model(rule_id="", **kwargs)  # type: ignore[operator]


def test_context_frame_requires_ordered_revisions_and_reason_for_missing_request() -> None:
    with pytest.raises(ValidationError, match="before_revision"):
        ContextFrame(
            id="context-invalid-revision",
            source_sequences=(1,),
            rule_id="context-frame.v1",
            source_sequence=1,
            before_revision=2,
            after_revision=1,
            before_state_hash="sha256:" + "a" * 64,
            after_state_hash="sha256:" + "b" * 64,
            before_state={},
            delta={},
            after_state={},
        )

    with pytest.raises(ValidationError, match="unavailable_reason"):
        ContextFrame(
            id="context-missing-request",
            source_sequences=(1,),
            rule_id="context-frame.v1",
            source_sequence=1,
            before_revision=0,
            after_revision=1,
            before_state_hash="sha256:" + "a" * 64,
            after_state_hash="sha256:" + "b" * 64,
            before_state={},
            delta={},
            after_state={},
            request_artifact_ref=None,
        )


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (
            ContextFrame,
            {
                "source_sequence": 1,
                "before_revision": 0,
                "after_revision": 1,
                "before_state_hash": "sha256:" + "a" * 64,
                "after_state_hash": "sha256:" + "b" * 64,
                "before_state": {},
                "delta": {},
                "after_state": {},
                "request_artifact_ref": "artifact:request",
            },
        ),
        (
            ArtifactIndexRecord,
            {
                "reference": "artifact:request",
                "kind": "request",
                "relative_path": "requests/request/input.json",
                "sha256": "a" * 64,
                "verification_status": "verified",
            },
        ),
        (
            ProjectionDiagnostic,
            {"severity": "warning", "code": "missing", "message": "Unavailable"},
        ),
    ],
)
def test_node_like_projection_models_require_id_and_positive_provenance(
    model: type[object], kwargs: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="id"):
        model(**kwargs)  # type: ignore[operator]

    with pytest.raises(ValidationError, match="source_sequences"):
        model(id="stable-id", source_sequences=(), **kwargs)  # type: ignore[operator]

    with pytest.raises(ValidationError, match="positive"):
        model(id="stable-id", source_sequences=(0,), **kwargs)  # type: ignore[operator]


def test_imported_event_payload_is_deeply_immutable_and_json_compatible() -> None:
    event = ImportedRunEvent(
        analysis_id="analysis-old",
        sequence=1,
        timestamp=None,
        event_type="turn.started",
        import_previous_hash="sha256:" + "0" * 64,
        import_hash="sha256:" + "1" * 64,
        source_coordinate=SourceCoordinate(
            path="context/context-events.jsonl", sequence=2, sha256="a" * 64
        ),
        source=EventSource(kind="observed", integrity="importer-integrity"),
        payload={"nested": {"values": ["original"]}},
    )

    with pytest.raises(TypeError):
        event.payload["nested"]["values"] += ("mutated",)
    with pytest.raises(AttributeError):
        event.payload["nested"]["values"].append("mutated")
    assert event.model_dump(mode="json")["payload"] == {
        "nested": {"values": ["original"]}
    }


def test_context_frame_states_are_deeply_immutable_and_json_compatible() -> None:
    frame = ContextFrame(
        id="context-1",
        source_sequences=(1,),
        rule_id="context-frame.v1",
        source_sequence=1,
        before_revision=0,
        after_revision=1,
        before_state_hash="sha256:" + "a" * 64,
        after_state_hash="sha256:" + "b" * 64,
        before_state={"nested": {"values": ["before"]}},
        delta={"nested": {"values": ["change"]}},
        after_state={"nested": {"values": ["after"]}},
        request_artifact_ref="artifact:request",
    )

    with pytest.raises(TypeError):
        frame.after_state["nested"]["values"] += ("mutated",)
    with pytest.raises(AttributeError):
        frame.before_state["nested"]["values"].append("mutated")
    assert frame.model_dump(mode="json")["after_state"] == {
        "nested": {"values": ["after"]}
    }


def test_artifact_index_records_are_deeply_immutable_and_json_compatible() -> None:
    record = ArtifactIndexRecord(
        id="artifact-record-1",
        source_sequences=(1,),
        reference="artifact:request",
        kind="request",
        relative_path="requests/request/input.json",
        sha256="a" * 64,
        verification_status="verified",
    )
    index = ArtifactIndex(analysis_id="analysis-1", records={record.reference: record})
    records = cast(dict[str, ArtifactIndexRecord], index.records)

    with pytest.raises(TypeError):
        records[record.reference] = record
    with pytest.raises(TypeError):
        records.update({"artifact:other": record})
    assert index.model_dump(mode="json")["records"] == {
        "artifact:request": record.model_dump(mode="json")
    }


def test_context_checkpoint_state_is_deeply_immutable_and_json_compatible() -> None:
    checkpoint = ContextCheckpoint(
        source_sequence=1,
        context_revision=1,
        state_hash="sha256:" + "a" * 64,
        state={"nested": {"values": ["checkpoint"]}},
    )

    with pytest.raises(TypeError):
        checkpoint.state["nested"]["values"] += ("mutated",)
    with pytest.raises(AttributeError):
        checkpoint.state["nested"]["values"].append("mutated")
    assert checkpoint.model_dump(mode="json")["state"] == {
        "nested": {"values": ["checkpoint"]}
    }
