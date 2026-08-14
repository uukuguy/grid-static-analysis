from __future__ import annotations

import pytest
from pydantic import ValidationError

from grid_agent.trajectory.events import EventSource, RunScope
from grid_agent.trajectory.projection_models import BusinessNode, ContextFrame
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


def test_context_frame_requires_ordered_revisions_and_reason_for_missing_request() -> None:
    with pytest.raises(ValidationError, match="before_revision"):
        ContextFrame(
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
