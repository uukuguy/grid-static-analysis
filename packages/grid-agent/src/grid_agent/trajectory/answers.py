"""Validated structured answer claims with current-run simulator lineage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from grid_agent.trajectory.events import StrictFrozenModel


class ReferenceVerifier(Protocol):
    def verify_result(self, reference: str) -> object: ...

    def verify_evidence(self, reference: str) -> object: ...


class AnswerClaim(StrictFrozenModel):
    statement: str = Field(min_length=1, max_length=1000)
    category: Literal[
        "topology",
        "constraint",
        "numerical_result",
        "risk_judgment",
        "offline_information",
    ]
    result_refs: tuple[str, ...] = Field(default=(), max_length=20)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def require_category_lineage(self) -> AnswerClaim:
        has_lineage = bool(self.result_refs or self.evidence_refs)
        if self.category == "offline_information" and has_lineage:
            raise ValueError("offline-information claim must not include simulator refs")
        if self.category != "offline_information" and not has_lineage:
            raise ValueError("simulator-backed claim requires result or evidence refs")
        return self


class AnswerSubmission(StrictFrozenModel):
    submission_id: str = Field(min_length=1)
    answer_output: str = Field(min_length=1)
    result_refs: tuple[str, ...]
    claim_evidence_refs: tuple[str, ...]
    claims: tuple[AnswerClaim, ...] = Field(max_length=50)


def validate_submission(
    draft: Mapping[str, Any],
    verifier: ReferenceVerifier,
    allowed_refs: Set[str],
) -> AnswerSubmission:
    """Validate a complete submission without examining its answer prose."""
    submission = AnswerSubmission.model_validate(draft)
    _require_reference_kind(submission.result_refs, "result", "result_refs")
    _require_reference_kind(
        submission.claim_evidence_refs,
        "evidence",
        "claim_evidence_refs",
    )
    claim_result_refs = _ordered_unique(
        reference
        for claim in submission.claims
        for reference in claim.result_refs
    )
    claim_evidence_refs = _ordered_unique(
        reference
        for claim in submission.claims
        for reference in claim.evidence_refs
    )

    undeclared_results = set(claim_result_refs).difference(submission.result_refs)
    if undeclared_results:
        raise ValueError("claim result refs must be declared in answer-level result_refs")
    undeclared_evidence = set(claim_evidence_refs).difference(
        submission.claim_evidence_refs
    )
    if undeclared_evidence:
        raise ValueError(
            "claim evidence refs must be declared in answer-level claim_evidence_refs"
        )

    unknown_refs = set(
        (*submission.result_refs, *submission.claim_evidence_refs)
    ).difference(allowed_refs)
    if unknown_refs:
        raise ValueError("claim reference is not known in the current run")

    for reference in _ordered_unique(submission.result_refs):
        verifier.verify_result(reference)
    for reference in _ordered_unique(submission.claim_evidence_refs):
        verifier.verify_evidence(reference)
    return submission


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _require_reference_kind(
    references: Iterable[str],
    kind: str,
    field: str,
) -> None:
    prefix = f"{kind}:sha256:"
    if any(
        not reference.startswith(prefix)
        or len(reference) != len(prefix) + 64
        or any(character not in "0123456789abcdef" for character in reference[len(prefix) :])
        for reference in references
    ):
        raise ValueError(f"{field} must contain only {kind}:sha256 references")


__all__ = ["AnswerClaim", "AnswerSubmission", "validate_submission"]
