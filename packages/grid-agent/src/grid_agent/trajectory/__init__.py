"""Native trajectory event protocol for grid-agent runs."""

from grid_agent.trajectory.canonical import canonical_json_bytes, sha256_ref
from grid_agent.trajectory.events import (
    Causation,
    ContextBoundary,
    EventDraft,
    EventRefs,
    EventSource,
    RunEvent,
    RunScope,
    build_event,
)

__all__ = [
    "Causation",
    "ContextBoundary",
    "EventDraft",
    "EventRefs",
    "EventSource",
    "RunEvent",
    "RunScope",
    "build_event",
    "canonical_json_bytes",
    "sha256_ref",
]
