from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PandapowerBinding(StrictModel):
    version: Literal["3.4.0"]
    operation: str
    limitations: tuple[str, ...] = ()


class CapabilityContract(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str
    package: str
    tool_name: str
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
    state_effect: Literal["none", "creates_context", "creates_result"]
    evidence_required: bool
    risk: Literal["catalog", "read_only_model", "read_only_analysis"]
    pandapower: PandapowerBinding | None
