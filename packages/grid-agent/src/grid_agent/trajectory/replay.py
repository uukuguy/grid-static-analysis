"""Common event interface for native and explicitly imported replay streams."""

from __future__ import annotations

from collections.abc import Mapping
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


class _FrozenDict(dict[str, Any]):
    """A JSON-compatible dictionary that rejects every in-place mutation."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        dict.__init__(self, values)

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("mapping is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable  # type: ignore[reportAssignmentType]
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[reportAssignmentType]
    setdefault = _immutable  # type: ignore[reportAssignmentType]
    update = _immutable  # type: ignore[reportAssignmentType]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


class SourceCoordinate(StrictFrozenModel):
    """Immutable location and digest of a record in an imported source file."""

    path: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@runtime_checkable
class ReplayEventLike(Protocol):
    """The validated event fields consumed by pure projection reducers."""

    @property
    def analysis_id(self) -> str: ...

    @property
    def sequence(self) -> int: ...

    @property
    def timestamp(self) -> str | None: ...

    @property
    def event_type(self) -> str: ...

    @property
    def scope(self) -> RunScope: ...

    @property
    def causation(self) -> Causation: ...

    @property
    def source(self) -> EventSource: ...

    @property
    def context(self) -> ContextBoundary: ...

    @property
    def refs(self) -> EventRefs: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


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
    payload: Mapping[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_payload(self) -> "ImportedRunEvent":
        object.__setattr__(self, "payload", _deep_freeze(self.payload))
        return self

    @model_validator(mode="after")
    def require_importer_integrity(self) -> "ImportedRunEvent":
        if self.source.kind != "observed":
            raise ValueError("imported event source must be observed")
        if self.source.integrity != "importer-integrity":
            raise ValueError("imported event requires importer-integrity")
        return self


__all__ = ["ImportedRunEvent", "ReplayEventLike", "SourceCoordinate"]
