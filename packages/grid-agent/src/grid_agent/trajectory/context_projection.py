"""Pure context-state time travel over a replay event stream."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.projection_models import ContextCheckpoint, ContextFrame, ContextTimeline
from grid_agent.trajectory.replay import ReplayEventLike


RULE_CONTEXT_FRAME = "context-frame/v1"
MISSING_REQUEST_INPUT = "legacy source did not capture model request input"


def _state_hash(state: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(canonical_json_bytes(state)).hexdigest()


def _copy_state(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _copy_value(item) for key, item in value.items()}
    return {}


def _copy_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_copy_value(item) for item in value]
    return value


def _delta(before: object, after: object) -> dict[str, Any]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(set(before) | set(after), key=str):
            name = str(key)
            if key not in before:
                if isinstance(after[key], Mapping):
                    result[name] = {"added": sorted(map(str, after[key]))}
                else:
                    result.setdefault("added", []).append(name)
            elif key not in after:
                if isinstance(before[key], Mapping):
                    result[name] = {"removed": sorted(map(str, before[key]))}
                else:
                    result.setdefault("removed", []).append(name)
            else:
                nested = _delta(before[key], after[key])
                if nested:
                    result[name] = nested
        return result
    return {} if before == after else {"before": _copy_value(before), "after": _copy_value(after)}


def _after_state(state: Mapping[str, Any], event: ReplayEventLike) -> dict[str, Any]:
    payload = event.payload
    snapshot = payload.get("after_state", payload.get("context_state"))
    if isinstance(snapshot, Mapping):
        return _copy_state(snapshot)
    # A native event may carry a materialized context-view payload directly.
    if event.event_type in {"context.projected", "context.injected"} and isinstance(payload.get("state"), Mapping):
        return _copy_state(payload["state"])
    return _copy_state(state)


def _request_refs(events: Sequence[ReplayEventLike]) -> dict[int, str | None]:
    next_ref: str | None = None
    links: dict[int, str | None] = {}
    for event in reversed(events):
        if event.event_type == "model.request.started":
            value = event.payload.get("artifact_ref")
            next_ref = value if isinstance(value, str) and value else None
        links[event.sequence] = next_ref
    return links


def project_context(
    events: Sequence[ReplayEventLike], artifacts: object, *, checkpoint_interval: int = 100
) -> ContextTimeline:
    """Return immutable state frames; ``artifacts`` is reserved for verified views."""
    del artifacts
    if checkpoint_interval < 1:
        raise ValueError("checkpoint_interval must be positive")
    if not events:
        return ContextTimeline(analysis_id="unknown")

    state: dict[str, Any] = {}
    frames: list[ContextFrame] = []
    checkpoints: list[ContextCheckpoint] = []
    requests = _request_refs(events)
    revision = 0
    for event in events:
        before = _copy_state(event.payload.get("before_state", state))
        before_revision = event.context.before_revision
        if before_revision is None:
            before_revision = revision
        after = _after_state(before, event)
        after_revision = event.context.after_revision
        if after_revision is None:
            after_revision = before_revision
        request_ref = requests[event.sequence]
        frame = ContextFrame(
            id=f"context:{event.analysis_id}:{event.sequence}",
            source_sequences=(event.sequence,),
            rule_id=RULE_CONTEXT_FRAME,
            source_sequence=event.sequence,
            before_revision=before_revision,
            after_revision=after_revision,
            before_state_hash=_state_hash(before),
            after_state_hash=_state_hash(after),
            before_state=before,
            delta=_delta(before, after),
            after_state=after,
            request_artifact_ref=request_ref,
            unavailable_reason=None if request_ref else MISSING_REQUEST_INPUT,
        )
        frames.append(frame)
        state, revision = after, after_revision
        if event.sequence % checkpoint_interval == 0 or event.event_type in {"turn.completed", "analysis.completed"}:
            checkpoints.append(ContextCheckpoint(source_sequence=event.sequence, context_revision=revision, state_hash=frame.after_state_hash, state=state))
    return ContextTimeline(analysis_id=events[0].analysis_id, frames=tuple(frames), checkpoints=tuple(checkpoints))


__all__ = ["MISSING_REQUEST_INPUT", "RULE_CONTEXT_FRAME", "project_context"]
