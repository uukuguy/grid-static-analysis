from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from grid_agent.analysis.integrity import ReferenceDiagnostic
from grid_agent.analysis.store import AnalysisContextStore
from grid_agent.analysis import turns as turns_module
from grid_agent.analysis.turns import StaleAnswerDraftError, TurnController
from grid_agent.analysis.workspace import AnalysisWorkspace


INPUT = {
    "copied_path": "input/instructions.md.txt",
    "source_path": "task.md.txt",
    "sha256": "a" * 64,
    "instruction_count": 2,
}

RUNTIME = {
    "provider": "test",
    "model": "scripted",
    "grid_capability_protocol": "1.0",
    "pandapower_version": "3.4.0",
}


@dataclass(frozen=True, slots=True)
class Harness:
    workspace: AnalysisWorkspace
    store: AnalysisContextStore
    turns: TurnController


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    workspace = AnalysisWorkspace.create(tmp_path / "runs", "analysis-test")
    store = AnalysisContextStore.initialize(workspace, input_record=INPUT, runtime_record=RUNTIME)
    turns = TurnController(workspace, store, audit_callback=lambda _claimed, _results: ())
    return Harness(workspace=workspace, store=store, turns=turns)


def test_turn_controller_rejects_stale_draft_and_archives_current_submission(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    write_draft(harness.workspace.active_answer_draft_path, first, answer="第一答")
    harness.turns.finalize(first, duration_seconds=1.0)
    second = harness.turns.start(2, "第二条")
    write_raw_draft(
        harness.workspace.active_answer_draft_path,
        turn_id=first.turn_id,
        turn_nonce=first.turn_nonce,
        answer="旧答",
    )

    with pytest.raises(StaleAnswerDraftError):
        harness.turns.finalize(second, duration_seconds=1.0)

    write_draft(harness.workspace.active_answer_draft_path, second, answer="第二答")
    completed = harness.turns.finalize(second, duration_seconds=1.2)
    assert completed.answer_output == "第二答"
    assert json.loads((harness.workspace.turn_path(2) / "answer.json").read_text(encoding="utf-8"))[
        "answer_output"
    ] == "第二答"
    assert [json.loads(line)["answer_output"] for line in harness.workspace.answers_path.read_text().splitlines()] == [
        "第一答",
        "第二答",
    ]


def test_turn_controller_archives_audit_diagnostics_without_mutating_answer(harness: Harness) -> None:
    diagnostic = ReferenceDiagnostic(
        category="missing_evidence",
        severity="error",
        reference="evidence:sha256:" + "f" * 64,
        message="claimed evidence ref is not in the current run",
        impact="impact",
        remediation="remediation",
    )
    turns = TurnController(harness.workspace, harness.store, audit_callback=lambda _claimed, _results: (diagnostic,))
    turn = turns.start(1, "引用证据")
    write_draft(
        harness.workspace.active_answer_draft_path,
        turn,
        answer="保持原文 result:sha256:" + "a" * 64,
        claim_evidence_refs=[diagnostic.reference],
    )

    completed = turns.finalize(turn, duration_seconds=0.5)

    assert completed.answer_output == "保持原文 result:sha256:" + "a" * 64
    assert completed.audit_diagnostics == (diagnostic,)
    assert json.loads((harness.workspace.turn_path(1) / "answer.json").read_text(encoding="utf-8"))[
        "answer_output"
    ] == completed.answer_output
    assert json.loads(harness.workspace.answers_path.read_text(encoding="utf-8"))["answer_output"] == completed.answer_output
    audit = json.loads((harness.workspace.turn_path(1) / "answer-audit.json").read_text(encoding="utf-8"))
    assert audit["diagnostics"][0]["message"] == diagnostic.message
    assert harness.store.snapshot.diagnostics[-1].event_type == "audit.diagnostic.recorded"
    assert harness.store.snapshot.turns[-1].status == "success"


def test_turn_controller_missing_draft_fails_turn_records_limitation_and_incremental_answer(harness: Harness) -> None:
    turn = harness.turns.start(1, "没有提交")
    assert not harness.workspace.active_answer_draft_path.exists()

    finalized = harness.turns.finalize(turn, duration_seconds=2.0)

    assert finalized.status == "failed"
    assert finalized.answer_path is None
    assert "execution limitation" in finalized.answer_output
    assert harness.store.snapshot.current_turn is None
    assert harness.store.snapshot.turns[-1].status == "failed"
    assert harness.store.snapshot.unresolved_limitations[-1].turn_id == turn.turn_id
    assert json.loads(harness.workspace.answers_path.read_text(encoding="utf-8"))["answer_output"] == finalized.answer_output
    assert not (harness.workspace.turn_path(1) / "answer.json").exists()


@pytest.mark.parametrize(
    ("draft_writer", "expected_error"),
    [
        (lambda path, turn: path.write_text("{not-json", encoding="utf-8"), "not valid JSON"),
        (lambda path, turn: path.write_text(json.dumps(["not", "object"]), encoding="utf-8"), "must be a JSON object"),
        (
            lambda path, turn: write_payload(
                path,
                {
                    "turn_id": turn.turn_id,
                    "turn_nonce": turn.turn_nonce,
                    "claim_evidence_refs": [],
                    "result_refs": [],
                },
            ),
            "must include answer_output",
        ),
        (
            lambda path, turn: write_payload(
                path,
                {
                    "turn_id": turn.turn_id,
                    "turn_nonce": turn.turn_nonce,
                    "answer_output": "答案",
                    "claim_evidence_refs": "not-a-list",
                    "result_refs": [],
                },
            ),
            "must include claim_evidence_refs",
        ),
        (
            lambda path, turn: write_payload(
                path,
                {
                    "turn_id": turn.turn_id,
                    "turn_nonce": turn.turn_nonce,
                    "answer_output": "答案",
                    "claim_evidence_refs": [],
                    "result_refs": [123],
                },
            ),
            "must include result_refs",
        ),
    ],
)
def test_turn_controller_malformed_current_draft_fails_turn_with_limitation_and_jsonl(
    harness: Harness,
    draft_writer,
    expected_error: str,
) -> None:
    turn = harness.turns.start(1, "提交坏草稿")
    draft_writer(harness.workspace.active_answer_draft_path, turn)

    finalized = harness.turns.finalize(turn, duration_seconds=0.75)

    assert finalized.status == "failed"
    assert finalized.answer_path is None
    assert expected_error in (finalized.error or "")
    assert expected_error in finalized.answer_output
    assert harness.store.snapshot.current_turn is None
    assert harness.store.snapshot.turns[-1].status == "failed"
    assert harness.store.snapshot.unresolved_limitations[-1].message == finalized.error
    assert json.loads(harness.workspace.answers_path.read_text(encoding="utf-8"))["answer_output"] == finalized.answer_output
    assert not (harness.workspace.turn_path(1) / "answer.json").exists()


def test_turn_start_atomically_replaces_active_turn_and_clears_active_draft(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    stale_draft = harness.workspace.active_answer_draft_path
    write_draft(stale_draft, first, answer="未完成")
    harness.turns.fail(first, error="model stopped", duration_seconds=0.1)

    second = harness.turns.start(2, "第二条")

    active_turn = json.loads(harness.workspace.active_turn_path.read_text(encoding="utf-8"))
    assert active_turn["turn_id"] == second.turn_id
    assert active_turn["turn_nonce"] == second.turn_nonce
    assert active_turn["turn_id"] != first.turn_id
    assert not stale_draft.exists()
    assert not list(harness.workspace.root_path.glob(".active-turn.json*.tmp"))


def test_turn_start_while_store_turn_active_preserves_active_files_and_context(harness: Harness) -> None:
    first = harness.turns.start(1, "第一条")
    write_draft(harness.workspace.active_answer_draft_path, first, answer="草稿")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    with pytest.raises(RuntimeError, match="active turn"):
        harness.turns.start(2, "第二条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_start_preserves_active_files_when_store_append_fails(harness: Harness) -> None:
    harness.workspace.active_turn_path.write_text('{"turn_id":"previous"}\n', encoding="utf-8")
    harness.workspace.active_answer_draft_path.write_text('{"answer_output":"previous"}\n', encoding="utf-8")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    def fail_append(*args, **kwargs):
        raise RuntimeError("store append failed")

    harness.store.append = fail_append

    with pytest.raises(RuntimeError, match="store append failed"):
        harness.turns.start(1, "第一条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_start_preserves_active_files_and_context_when_filesystem_activation_fails(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.workspace.active_turn_path.write_text('{"turn_id":"previous"}\n', encoding="utf-8")
    harness.workspace.active_answer_draft_path.write_text('{"answer_output":"previous"}\n', encoding="utf-8")
    active_record_before = harness.workspace.active_turn_path.read_text(encoding="utf-8")
    draft_before = harness.workspace.active_answer_draft_path.read_text(encoding="utf-8")
    context_before = harness.store.snapshot

    def fail_active_record_write(path: Path, payload: object) -> bytes:
        if path == harness.workspace.active_turn_path:
            raise OSError("simulated active turn write failure")
        raise AssertionError(f"unexpected JSON write: {path}")

    monkeypatch.setattr(turns_module, "_write_json_atomic", fail_active_record_write)

    with pytest.raises(OSError, match="simulated active turn write failure"):
        harness.turns.start(1, "第一条")

    assert harness.workspace.active_turn_path.read_text(encoding="utf-8") == active_record_before
    assert harness.workspace.active_answer_draft_path.read_text(encoding="utf-8") == draft_before
    assert harness.store.snapshot == context_before


def test_turn_context_hashes_nonce_without_recording_raw_nonce(harness: Harness) -> None:
    turn = harness.turns.start(1, "哈希 nonce")

    snapshot_text = harness.workspace.context_snapshot_path.read_text(encoding="utf-8")
    events_text = harness.workspace.context_events_path.read_text(encoding="utf-8")

    assert turn.turn_nonce in harness.workspace.active_turn_path.read_text(encoding="utf-8")
    assert turn.turn_nonce not in snapshot_text
    assert turn.turn_nonce not in events_text
    assert harness.store.snapshot.current_turn is not None
    assert harness.store.snapshot.current_turn.nonce_sha256 == sha256(turn.turn_nonce.encode("utf-8")).hexdigest()


def write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_draft(
    path: Path,
    turn,
    *,
    answer: str,
    claim_evidence_refs: list[str] | None = None,
    result_refs: list[str] | None = None,
) -> None:
    write_raw_draft(
        path,
        turn_id=turn.turn_id,
        turn_nonce=turn.turn_nonce,
        answer=answer,
        claim_evidence_refs=claim_evidence_refs,
        result_refs=result_refs,
    )


def write_raw_draft(
    path: Path,
    *,
    turn_id: str,
    turn_nonce: str,
    answer: str,
    claim_evidence_refs: list[str] | None = None,
    result_refs: list[str] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "turn_id": turn_id,
                "turn_nonce": turn_nonce,
                "answer_output": answer,
                "claim_evidence_refs": claim_evidence_refs or [],
                "result_refs": result_refs or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
