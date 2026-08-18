from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseRequirements(StrictModel):
    required_capabilities: tuple[str, ...] = ()
    forbidden_capabilities: tuple[str, ...] = ()
    max_tool_calls: int = Field(ge=0)
    requires_evidence: bool


class OracleSpec(StrictModel):
    kind: Literal["structured", "semantic", "knowledge", "limitation"]
    evaluator: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ValidationCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    question: str = Field(min_length=1)
    suites: tuple[str, ...]
    model: str | None = None
    requirements: CaseRequirements
    oracle: OracleSpec

    @model_validator(mode="after")
    def require_one_capability_for_structured_oracle(self) -> "ValidationCase":
        if self.oracle.kind == "structured" and len(self.requirements.required_capabilities) != 1:
            raise ValueError("structured validation cases require exactly one capability")
        if self.oracle.kind == "semantic" and not self.requirements.required_capabilities:
            raise ValueError("semantic validation cases require at least one capability")
        return self


def load_cases(root: Path) -> tuple[ValidationCase, ...]:
    paths = sorted((Path(root) / "suites").glob("*/*.json"))
    cases = tuple(ValidationCase.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in paths)
    identifiers = [case.id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("validation case ids must be unique")
    return cases
