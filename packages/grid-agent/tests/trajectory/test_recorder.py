from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from grid_agent.trajectory.artifacts import ImmutableArtifactRegistry
from grid_agent.trajectory.events import EventDraft, EventRefs, RunScope
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


def test_recorder_accepts_model_response_usage_fields(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path)
    pointer = registry.write_json(
        "model-response", "analysis-test-t001-r001", {"content": "answer"}
    )
    recorder = RunEventRecorder(
        tmp_path / "events.jsonl",
        "analysis-test",
        artifact_registry=registry,
    )

    event = recorder.append(
        EventDraft(
            event_type="model.response.completed",
            payload={
                "artifact_ref": pointer.ref,
                "input_tokens": 120,
                "output_tokens": 45,
            },
        )
    )

    assert event.payload["input_tokens"] == 120
    assert event.payload["output_tokens"] == 45
    assert RunEventReader(recorder.events_path).read_prefix().events == (event,)
    recorder.close()


@pytest.mark.parametrize("reference_location", ["payload", "refs"])
def test_recorder_rejects_unregistered_artifact_references(
    tmp_path: Path, reference_location: str
) -> None:
    run_root = tmp_path / "run"
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-test",
        artifact_registry=ImmutableArtifactRegistry(run_root),
    )
    fake_ref = "artifact:sha256:" + "a" * 64
    draft = (
        EventDraft(
            event_type="model.response.completed",
            payload={"artifact_ref": fake_ref},
        )
        if reference_location == "payload"
        else EventDraft(
            event_type="analysis.started",
            refs=EventRefs(produced=(fake_ref,)),
            payload={},
        )
    )

    with pytest.raises(RecorderIntegrityError, match="registered and verified"):
        recorder.append(draft)

    assert not recorder.events_path.exists()
    recorder.close()


def test_recorder_accepts_registered_digest_verified_artifact_pointer(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    pointer = registry.write_json(
        "model-response", "analysis-test-t001-r001", {"content": "answer"}
    )
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-test",
        artifact_registry=registry,
    )

    event = recorder.append(
        EventDraft(
            event_type="model.response.completed",
            payload={"artifact_ref": pointer.ref},
        )
    )

    assert event.payload["artifact_ref"] == pointer.ref
    assert RunEventReader(recorder.events_path).read_prefix().events == (event,)
    recorder.close()


@pytest.mark.parametrize(
    ("event_type", "reference_field"),
    [
        ("business.claim.declared", "result_refs"),
        ("business.claim.declared", "evidence_refs"),
        ("answer.submitted", "result_refs"),
        ("answer.submitted", "evidence_refs"),
    ],
)
def test_recorder_rejects_unregistered_artifact_claim_and_answer_references(
    tmp_path: Path, event_type: str, reference_field: str
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    answer_pointer = registry.write_json("answer", "submission-1", {"answer": "ok"})
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-test",
        artifact_registry=registry,
    )
    payload: dict[str, object] = {
        "submission_id": "submission-1",
        "result_refs": [],
        "evidence_refs": [],
    }
    if event_type == "business.claim.declared":
        payload.update(
            statement="The registered network has a constraint.",
            category="constraint",
        )
    else:
        payload["artifact_ref"] = answer_pointer.ref
    payload[reference_field] = ["artifact:sha256:" + "a" * 64]

    with pytest.raises(RecorderIntegrityError, match="registered and verified"):
        recorder.append(EventDraft(event_type=event_type, payload=payload))

    assert not recorder.events_path.exists()
    recorder.close()


@pytest.mark.parametrize(
    ("event_type", "reference_field", "kind", "identity", "relative_path"),
    [
        (
            "business.claim.declared",
            "result_refs",
            "result",
            "result:sha256:" + "a" * 64,
            "evidence/results/powerflow-" + "a" * 64 + ".json",
        ),
        (
            "business.claim.declared",
            "evidence_refs",
            "evidence",
            "evidence:sha256:" + "b" * 64,
            "evidence/network-facts/network-fact-" + "b" * 64 + ".json",
        ),
        (
            "answer.submitted",
            "result_refs",
            "result",
            "result:sha256:" + "c" * 64,
            "evidence/results/powerflow-" + "c" * 64 + ".json",
        ),
        (
            "answer.submitted",
            "evidence_refs",
            "evidence",
            "evidence:sha256:" + "d" * 64,
            "evidence/network-facts/network-fact-" + "d" * 64 + ".json",
        ),
    ],
)
def test_recorder_accepts_registered_artifact_claim_and_answer_references(
    tmp_path: Path,
    event_type: str,
    reference_field: str,
    kind: str,
    identity: str,
    relative_path: str,
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    path = run_root / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"preserve":"exact bytes"}\n')
    registered_pointer = registry.register_existing(kind, identity, path)
    answer_pointer = registry.write_json("answer", "submission-1", {"answer": "ok"})
    recorder = RunEventRecorder(
        run_root / "events/run-events.jsonl",
        "analysis-test",
        artifact_registry=registry,
    )
    payload: dict[str, object] = {
        "submission_id": "submission-1",
        "result_refs": [],
        "evidence_refs": [],
        reference_field: [registered_pointer.ref],
    }
    if event_type == "business.claim.declared":
        payload.update(
            statement="The registered network has a constraint.",
            category="constraint",
        )
    else:
        payload["artifact_ref"] = answer_pointer.ref

    event = recorder.append(EventDraft(event_type=event_type, payload=payload))

    assert event.payload[reference_field] == [registered_pointer.ref]
    assert RunEventReader(recorder.events_path).read_prefix().events == (event,)
    recorder.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "severity": "error",
            "category": "provider",
            "message": "provider returned sk-secret",
        },
        {
            "severity": "error",
            "category": "provider",
            "message": "safe",
            "api_key": "not-for-storage",
        },
        {
            "severity": "error",
            "category": "provider",
            "message": "safe",
            "hidden_reasoning": "private model reasoning",
        },
    ],
)
def test_recorder_rejects_credential_values_and_prohibited_exact_fields(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    recorder = RunEventRecorder(
        tmp_path / "events.jsonl", "analysis-test", secret_values={"sk-secret"}
    )
    unsafe_draft = EventDraft.model_construct(
        event_type="audit.diagnostic.recorded", payload=payload
    )

    with pytest.raises(RecorderIntegrityError, match="prohibited content"):
        recorder.append(unsafe_draft)

    assert not recorder.events_path.exists()
    recorder.close()


def test_concurrent_appends_preserve_contiguous_hash_chain(tmp_path: Path) -> None:
    recorder = RunEventRecorder(tmp_path / "events.jsonl", "analysis-test")

    with ThreadPoolExecutor(max_workers=8) as executor:
        recorded = tuple(
            executor.map(
                recorder.append,
                (
                    EventDraft(event_type="analysis.started", payload={})
                    for _ in range(40)
                ),
            )
        )

    prefix = RunEventReader(recorder.events_path).read_prefix()
    assert prefix.failure is None
    assert [event.sequence for event in prefix.events] == list(range(1, 41))
    assert sorted(event.event_hash for event in prefix.events) == sorted(
        event.event_hash for event in recorded
    )
    recorder.close()


def test_competing_recorder_is_rejected_until_owner_closes(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    owner = RunEventRecorder(path, "analysis-owner")

    with pytest.raises(RecorderIntegrityError, match="already owned"):
        RunEventRecorder(path, "analysis-competitor")

    owner.close()
    successor = RunEventRecorder(path, "analysis-successor")
    successor.close()


def test_recorder_rejects_preexisting_nonempty_log(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("existing trajectory\n")

    with pytest.raises(RecorderIntegrityError, match="already contains events"):
        RunEventRecorder(path, "analysis-test")

    path.unlink()
    successor = RunEventRecorder(path, "analysis-successor")
    successor.close()


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

    monkeypatch.undo()
    recorder.events_path.unlink(missing_ok=True)
    replacement = RunEventRecorder(recorder.events_path, "analysis-replacement")
    replacement.close()
