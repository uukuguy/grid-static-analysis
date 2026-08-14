from __future__ import annotations

import os
from pathlib import Path

import pytest

from grid_agent.trajectory.events import EventDraft, RunScope
from grid_agent.trajectory.reader import RunEventReader
from grid_agent.trajectory.recorder import RecorderIntegrityError, RunEventRecorder


def test_recorder_appends_fsyncs_then_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_fsync = os.fsync
    monkeypatch.setattr(
        os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
    )
    recorder = RunEventRecorder(
        tmp_path / "events/run-events.jsonl",
        "analysis-test",
        subscribers=(lambda event: calls.append(f"publish:{event.sequence}"),),
    )

    first = recorder.append(EventDraft(event_type="analysis.started", payload={}))
    second = recorder.append(
        EventDraft(
            event_type="turn.started",
            scope=RunScope(turn_id="analysis-test-t001"),
            payload={"ordinal": 1, "instruction_sha256": "a" * 64},
        )
    )

    assert calls == ["fsync", "publish:1", "fsync", "publish:2"]
    assert second.previous_event_hash == first.event_hash
    assert RunEventReader(recorder.events_path).read_prefix().events == (first, second)


def test_subscriber_failure_does_not_change_the_durable_log(tmp_path: Path) -> None:
    def broken_subscriber(_: object) -> None:
        raise RuntimeError("subscriber unavailable")

    recorder = RunEventRecorder(
        tmp_path / "events/run-events.jsonl",
        "analysis-test",
        subscribers=(broken_subscriber,),
    )

    event = recorder.append(EventDraft(event_type="analysis.started", payload={}))

    assert RunEventReader(recorder.events_path).read_prefix().events == (event,)


def test_recorder_rejects_secret_and_reasoning_fields(tmp_path: Path) -> None:
    recorder = RunEventRecorder(
        tmp_path / "events.jsonl", "analysis-test", secret_values={"sk-secret"}
    )

    with pytest.raises(RecorderIntegrityError, match="prohibited content"):
        recorder.append(
            EventDraft(
                event_type="audit.diagnostic.recorded",
                payload={
                    "severity": "error",
                    "category": "provider",
                    "message": "token=sk-secret",
                },
            )
        )
    with pytest.raises(RecorderIntegrityError, match="prohibited content"):
        recorder.append(
            EventDraft(
                event_type="audit.diagnostic.recorded",
                payload={
                    "severity": "error",
                    "category": "provider",
                    "message": "chain of thought: private model reasoning",
                },
            )
        )

    assert not recorder.events_path.exists()


@pytest.mark.parametrize("failure", ["short_write", "fsync"])
def test_durability_failures_close_the_recorder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    recorder = RunEventRecorder(tmp_path / "events/run-events.jsonl", "analysis-test")
    if failure == "short_write":
        real_open = Path.open

        class ShortWriteStream:
            def __init__(self, stream: object) -> None:
                self._stream = stream

            def __enter__(self) -> "ShortWriteStream":
                return self

            def __exit__(self, *args: object) -> None:
                self._stream.close()  # type: ignore[union-attr]

            def write(self, value: bytes) -> int:
                return max(0, len(value) - 1)

            def flush(self) -> None:
                return None

            def fileno(self) -> int:
                return self._stream.fileno()  # type: ignore[union-attr]

        monkeypatch.setattr(
            Path,
            "open",
            lambda path, *args, **kwargs: ShortWriteStream(
                real_open(path, *args, **kwargs)
            ),
        )
    else:
        monkeypatch.setattr(os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(RecorderIntegrityError, match="trajectory append failed"):
        recorder.append(EventDraft(event_type="analysis.started", payload={}))
    with pytest.raises(RecorderIntegrityError, match="recorder is closed"):
        recorder.append(EventDraft(event_type="analysis.started", payload={}))
