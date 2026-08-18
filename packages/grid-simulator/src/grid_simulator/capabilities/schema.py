from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PandapowerBinding(StrictModel):
    version: Literal["3.4.0"]
    operation: str
    limitations: tuple[str, ...] = ()


class CapabilityContextEffect(StrictModel):
    requires_state: tuple[str, ...]
    consumes_state: tuple[str, ...]
    produces_state: tuple[str, ...]
    invalidates_state: tuple[str, ...] = ()
    result_kind: str | None = None
    projector: str


class CapabilityContract(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str
    package: str
    tool_name: str
    availability: Literal["published", "not_published", "not_applicable", "unavailable", "failed"]
    title: str
    purpose: str
    applies_to: tuple[str, ...]
    not_for: tuple[str, ...]
    terms: dict[Literal["zh", "en"], tuple[str, ...]]
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    requires: tuple[str, ...]
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    common_next: tuple[str, ...]
    errors: tuple[str, ...]
    recovery: dict[str, tuple[str, ...]]
    context_effect: CapabilityContextEffect
    state_effect: Literal["none", "creates_context", "creates_result"]
    evidence_required: bool
    risk: Literal["catalog", "read_only_model", "read_only_analysis", "model_revision"]
    pandapower: PandapowerBinding | None
