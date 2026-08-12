from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GridCapabilityRequest(StrictModel):
    protocol: Literal["grid-capability"] = "grid-capability"
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str = Field(min_length=1)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    arguments: dict[str, JsonValue]


class CapabilityError(StrictModel):
    code: str
    phase: Literal["parse", "resolve", "validate", "execute", "persist"]
    message: str
    retryable: bool = False
    state_effect: Literal["none", "committed"] = "none"
    allowed_recovery_actions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    details: dict[str, JsonValue] = Field(default_factory=dict)


class GridCapabilityResponse(StrictModel):
    protocol: Literal["grid-capability"] = "grid-capability"
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: CapabilityError | None = None

    @model_validator(mode="after")
    def check_payload(self) -> GridCapabilityResponse:
        if self.ok and (self.result is None or self.error is not None):
            raise ValueError("successful response requires only result")
        if not self.ok and (self.error is None or self.result is not None):
            raise ValueError("failed response requires only error")
        return self
