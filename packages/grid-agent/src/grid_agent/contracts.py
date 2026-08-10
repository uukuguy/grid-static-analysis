from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AttemptStatus(StrEnum):
    ANSWERED_WITH_EVIDENCE = "answered_with_evidence"
    ANSWERED_FROM_GENERAL_KNOWLEDGE = "answered_from_general_knowledge"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    EXECUTION_FAILED = "execution_failed"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)

    @classmethod
    def from_text(cls, question: str) -> "RunRequest":
        return cls(question_id=f"q-{uuid4().hex}", question=question.strip())


class AnswerEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer_output: str
