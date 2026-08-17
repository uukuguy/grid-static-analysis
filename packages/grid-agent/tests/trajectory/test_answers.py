from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from grid_agent.trajectory.answers import AnswerClaim, validate_submission


RESULT_REF = "result:sha256:" + "a" * 64
EVIDENCE_REF = "evidence:sha256:" + "b" * 64


class RecordingVerifier:
    def __init__(self) -> None:
        self.results: list[str] = []
        self.evidence: list[str] = []

    def verify_result(self, reference: str) -> object:
        self.results.append(reference)
        return object()

    def verify_evidence(self, reference: str) -> object:
        self.evidence.append(reference)
        return object()


def submission_draft(**overrides: Any) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "submission_id": "submission-1",
        "answer_output": "Line 11 reaches 132.51 percent loading.",
        "result_refs": [RESULT_REF],
        "claim_evidence_refs": [EVIDENCE_REF],
        "claims": [
            {
                "statement": "Line 11 reaches 132.51 percent loading",
                "category": "numerical_result",
                "result_refs": [RESULT_REF],
                "evidence_refs": [EVIDENCE_REF],
            }
        ],
    }
    draft.update(overrides)
    return draft


def test_validate_submission_verifies_declared_claim_lineage() -> None:
    verifier = RecordingVerifier()

    submission = validate_submission(
        submission_draft(), verifier, {RESULT_REF, EVIDENCE_REF}
    )

    assert submission.submission_id == "submission-1"
    assert verifier.results == [RESULT_REF]
    assert verifier.evidence == [EVIDENCE_REF]


def test_simulator_claim_requires_verified_current_run_reference() -> None:
    verifier = RecordingVerifier()

    with pytest.raises(ValidationError, match="simulator-backed claim"):
        validate_submission(
            submission_draft(
                result_refs=[],
                claim_evidence_refs=[],
                claims=[
                    {
                        "statement": "unsupported",
                        "category": "numerical_result",
                        "result_refs": [],
                        "evidence_refs": [],
                    }
                ],
            ),
            verifier,
            set(),
        )

    assert verifier.results == []
    assert verifier.evidence == []


def test_offline_information_claim_forbids_simulator_lineage() -> None:
    with pytest.raises(ValidationError, match="offline-information claim"):
        AnswerClaim(
            statement="General power-system information",
            category="offline_information",
            result_refs=(RESULT_REF,),
        )


def test_offline_information_claim_is_accepted_without_run_evidence() -> None:
    verifier = RecordingVerifier()

    submission = validate_submission(
        submission_draft(
            answer_output="General power-system information.",
            result_refs=[],
            claim_evidence_refs=[],
            claims=[
                {
                    "statement": "General power-system information",
                    "category": "offline_information",
                    "result_refs": [],
                    "evidence_refs": [],
                }
            ],
        ),
        verifier,
        set(),
    )

    assert submission.claims[0].category == "offline_information"
    assert verifier.results == []
    assert verifier.evidence == []


def test_claim_refs_must_be_declared_at_answer_level() -> None:
    with pytest.raises(ValueError, match="answer-level result_refs"):
        validate_submission(
            submission_draft(result_refs=[]),
            RecordingVerifier(),
            {RESULT_REF, EVIDENCE_REF},
        )

    with pytest.raises(ValueError, match="answer-level claim_evidence_refs"):
        validate_submission(
            submission_draft(claim_evidence_refs=[]),
            RecordingVerifier(),
            {RESULT_REF, EVIDENCE_REF},
        )


def test_claim_refs_must_be_controller_known() -> None:
    with pytest.raises(ValueError, match="not known in the current run"):
        validate_submission(
            submission_draft(), RecordingVerifier(), {RESULT_REF}
        )


def test_submission_rejects_misclassified_answer_level_references() -> None:
    with pytest.raises(ValueError, match="result_refs must contain only result"):
        validate_submission(
            submission_draft(
                result_refs=[EVIDENCE_REF],
                claims=[
                    {
                        "statement": "topology fact",
                        "category": "topology",
                        "result_refs": [EVIDENCE_REF],
                        "evidence_refs": [EVIDENCE_REF],
                    }
                ],
            ),
            RecordingVerifier(),
            {EVIDENCE_REF},
        )

    with pytest.raises(
        ValueError,
        match="claim_evidence_refs must contain only evidence",
    ):
        validate_submission(
            submission_draft(
                result_refs=[RESULT_REF],
                claim_evidence_refs=[RESULT_REF],
                claims=[
                    {
                        "statement": "numerical fact",
                        "category": "numerical_result",
                        "result_refs": [RESULT_REF],
                        "evidence_refs": [RESULT_REF],
                    }
                ],
            ),
            RecordingVerifier(),
            {RESULT_REF},
        )


def test_claim_and_submission_bounds_are_closed() -> None:
    with pytest.raises(ValidationError, match="at most 1000 characters"):
        AnswerClaim(
            statement="x" * 1001,
            category="offline_information",
        )

    with pytest.raises(ValidationError, match="at most 20 items"):
        AnswerClaim(
            statement="bounded refs",
            category="numerical_result",
            result_refs=tuple(
                f"result:sha256:{index:064x}" for index in range(21)
            ),
        )

    with pytest.raises(ValidationError, match="at most 50 items"):
        validate_submission(
            submission_draft(
                result_refs=[],
                claim_evidence_refs=[],
                claims=[
                    {
                        "statement": f"offline {index}",
                        "category": "offline_information",
                        "result_refs": [],
                        "evidence_refs": [],
                    }
                    for index in range(51)
                ],
            ),
            RecordingVerifier(),
            set(),
        )
