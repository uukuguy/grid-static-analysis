from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class SimulatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"]
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    arguments: dict[str, JsonValue]


class OperationError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, JsonValue] = Field(default_factory=dict)


class SimulatorResponse(BaseModel):
    protocol_version: Literal["1.0"] = "1.0"
    request_id: str
    ok: bool
    result: dict[str, JsonValue] | None = None
    error: OperationError | None = None
