from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import EventDraft, RunScope, build_event
from grid_agent.trajectory.reader import RunEventReader


def write_three_valid_events(tmp_path: Path) -> Path:
    path = tmp_path / "events/run-events.jsonl"
    first = build_event(
        EventDraft(event_type="analysis.started", payload={}),
        analysis_id="analysis-test",
        sequence=1,
        timestamp=datetime(2026, 8, 14, tzinfo=UTC),
        previous_event_hash="sha256:" + "0" * 64,
    )
    second = build_event(
        EventDraft(
            event_type="turn.started",
            scope=RunScope(turn_id="analysis-test-t001"),
            payload={"ordinal": 1, "instruction_sha256": "a" * 64},
        ),
        analysis_id="analysis-test",
        sequence=2,
        timestamp=datetime(2026, 8, 14, tzinfo=UTC) + timedelta(seconds=1),
        previous_event_hash=first.event_hash,
    )
    third = build_event(
        EventDraft(
            event_type="turn.completed",
            scope=RunScope(turn_id="analysis-test-t001"),
            payload={"status": "success"},
        ),
        analysis_id="analysis-test",
        sequence=3,
        timestamp=datetime(2026, 8, 14, tzinfo=UTC) + timedelta(seconds=2),
        previous_event_hash=second.event_hash,
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"".join(canonical_json_bytes(event.model_dump(mode="json")) for event in (first, second, third)))
    return path


def test_reader_stops_at_first_hash_mismatch(tmp_path: Path) -> None:
    path = write_three_valid_events(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["payload"]["ordinal"] = 99
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        )
    )

    prefix = RunEventReader(path).read_prefix()

    assert [event.sequence for event in prefix.events] == [1]
    assert prefix.failure is not None
    assert prefix.failure.line_number == 2
    assert prefix.failure.code == "event_hash_mismatch"


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        (b"not json\n", "malformed_json"),
        (b"\n", "malformed_json"),
        (b'{"event_type":"future.required"}\n', "unknown_event"),
        (b'{"sequence":1}\n', "invalid_event"),
    ],
)
def test_reader_rejects_untrusted_first_line(
    tmp_path: Path, replacement: bytes, code: str
) -> None:
    path = tmp_path / "events/run-events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(replacement)

    prefix = RunEventReader(path).read_prefix()

    assert prefix.events == ()
    assert prefix.failure is not None
    assert prefix.failure.line_number == 1
    assert prefix.failure.code == code


@pytest.mark.parametrize("constant", ["Infinity", "-Infinity", "NaN"])
def test_reader_rejects_raw_non_finite_json_constants(
    tmp_path: Path, constant: str
) -> None:
    path = write_three_valid_events(tmp_path)
    rows = path.read_text().splitlines()
    rows[0] = rows[0].replace(
        '"event_type":"analysis.started"', '"event_type":"turn.completed"'
    )
    rows[0] = rows[0].replace(
        '"payload":{}',
        f'"payload":{{"duration_seconds":{constant},"status":"success"}}',
    )
    path.write_text("\n".join(rows) + "\n")

    prefix = RunEventReader(path).read_prefix()

    assert prefix.events == ()
    assert prefix.failure is not None
    assert prefix.failure.line_number == 1
    assert prefix.failure.code == "malformed_json"


@pytest.mark.parametrize(
    "member",
    [
        "schema_version",
        "analysis_id",
        "sequence",
        "timestamp",
        "event_type",
        "previous_event_hash",
        "event_hash",
        "scope",
        "causation",
        "source",
        "context",
        "refs",
        "payload",
    ],
)
def test_reader_requires_every_native_envelope_member(
    tmp_path: Path, member: str
) -> None:
    path = write_three_valid_events(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    del rows[0][member]
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))

    prefix = RunEventReader(path).read_prefix()

    assert prefix.events == ()
    assert prefix.failure is not None
    assert prefix.failure.line_number == 1
    assert prefix.failure.code == "invalid_event"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda row: row.__setitem__("sequence", 3), "sequence_gap"),
        (
            lambda row: row.__setitem__("previous_event_hash", "sha256:" + "b" * 64),
            "previous_hash_mismatch",
        ),
        (
            lambda row: row.__setitem__(
                "scope", {"turn_id": None, "step_id": "orphan-step"}
            ),
            "invalid_event",
        ),
        (
            lambda row: row.__setitem__("event_type", "future.required"),
            "unknown_event",
        ),
    ],
)
def test_reader_stops_at_first_invalid_record(
    tmp_path: Path, mutate: object, code: str
) -> None:
    path = write_three_valid_events(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    mutate(rows[1])  # type: ignore[operator]
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))

    prefix = RunEventReader(path).read_prefix()

    assert [event.sequence for event in prefix.events] == [1]
    assert prefix.failure is not None
    assert prefix.failure.line_number == 2
    assert prefix.failure.code == code
