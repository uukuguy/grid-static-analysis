from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from grid_agent.trajectory.legacy_v02 import LegacyImportError, LegacyV02Importer


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(root: Path) -> Path:
    run = root / "analysis-old"
    _write(run / "manifest.json", {"analysis_id": "analysis-old", "total_turns": 1})
    _write(
        run / "context/context-events.jsonl",
        {"analysis_id": "analysis-old", "sequence": 1, "event_type": "turn.started", "turn_id": "analysis-old-t001", "payload": {"ordinal": 1}, "previous_revision": 0, "next_revision": 1},
    )
    _write(
        run / "trace/events.jsonl",
        {"sequence": 1, "event": "tool_result", "payload": {"toolCallId": "call-1", "capability": "model.list", "ok": True}, "turn_id": "analysis-old-t001"},
    )
    return run


def _digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


def test_v02_import_is_deterministic_and_preserves_source_files(tmp_path: Path) -> None:
    run = _fixture(tmp_path)
    before = _digests(run)
    first = LegacyV02Importer(run).import_run()
    second = LegacyV02Importer(run).import_run()
    assert first == second
    assert _digests(run) == before
    assert all(event.schema_version == "grid-run-import-event/1.0" for event in first.events)


def test_v02_import_does_not_invent_missing_request_input(tmp_path: Path) -> None:
    imported = LegacyV02Importer(_fixture(tmp_path)).import_run()
    assert not any(event.event_type == "model.request.started" for event in imported.events)
    assert "model request input unavailable" in {diagnostic.message for diagnostic in imported.diagnostics}


def test_v02_import_normalizes_top_level_trace_type_and_camel_case_call_id(tmp_path: Path) -> None:
    run = _fixture(tmp_path)
    (run / "trace/events.jsonl").write_text(
        "\n".join(
            json.dumps(value)
            for value in (
                {"sequence": 1, "type": "tool_execution_start", "toolCallId": "call-1", "toolName": "model.list", "turn_id": "analysis-old-t001"},
                {"sequence": 2, "type": "tool_result", "toolCallId": "call-1", "toolName": "model.list", "ok": True, "turn_id": "analysis-old-t001"},
            )
        ) + "\n",
        encoding="utf-8",
    )

    events = LegacyV02Importer(run).import_run().events

    assert [(event.event_type, event.scope.tool_call_id) for event in events if event.event_type.startswith("tool.")] == [
        ("tool.started", "call-1"), ("tool.completed", "call-1")
    ]


def test_v02_import_rejects_invalid_present_context_source(tmp_path: Path) -> None:
    run = _fixture(tmp_path)
    (run / "context/context-events.jsonl").write_text('{"event_type": "turn.started"}\n', encoding="utf-8")

    with pytest.raises(LegacyImportError, match="context/context-events.jsonl:1.*analysis_id"):
        LegacyV02Importer(run).import_run()


def test_v02_import_emits_records_or_unavailable_diagnostics_for_every_legacy_source(tmp_path: Path) -> None:
    imported = LegacyV02Importer(_fixture(tmp_path)).import_run()

    messages = {item.code for item in imported.diagnostics}
    paths = {event.source_coordinate.path for event in imported.events}
    assert "manifest.json" in paths
    assert "context/context-events.jsonl" in paths
    assert "trace/events.jsonl" in paths
    assert {"pi-unavailable", "turn-artifacts-unavailable", "report-unavailable"} <= messages
