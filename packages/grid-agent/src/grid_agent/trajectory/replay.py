"""Common event interface for native and explicitly imported replay streams."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventRefs,
    EventSource,
    RunScope,
    StrictFrozenModel,
)


class SourceCoordinate(StrictFrozenModel):
    """Immutable location and digest of a record in an imported source file."""

    path: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@runtime_checkable
class ReplayEventLike(Protocol):
    """The validated event fields consumed by pure projection reducers."""

    analysis_id: str
    sequence: int
    timestamp: str | None
    event_type: str
    scope: RunScope
    causation: Causation
    source: EventSource
    context: ContextBoundary
    refs: EventRefs
    payload: dict[str, Any]


class ImportedRunEvent(StrictFrozenModel):
    """Normalized legacy event, distinct from authoritative native events."""

    schema_version: Literal["grid-run-import-event/1.0"] = "grid-run-import-event/1.0"
    analysis_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    timestamp: str | None
    event_type: str = Field(min_length=1)
    import_previous_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    import_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_coordinate: SourceCoordinate
    scope: RunScope = Field(default_factory=RunScope)
    causation: Causation = Field(default_factory=Causation)
    source: EventSource
    context: ContextBoundary = Field(default_factory=ContextBoundary)
    refs: EventRefs = Field(default_factory=EventRefs)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_importer_integrity(self) -> "ImportedRunEvent":
        if self.source.kind != "observed":
            raise ValueError("imported event source must be observed")
        if self.source.integrity != "importer-integrity":
            raise ValueError("imported event requires importer-integrity")
        return self


__all__ = ["ImportedRunEvent", "ReplayEventLike", "SourceCoordinate"]
