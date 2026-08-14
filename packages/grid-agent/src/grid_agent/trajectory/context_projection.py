"""Pure context-state time travel over a replay event stream."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from grid_agent.trajectory.artifacts import ArtifactPointer
from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.projection_models import ContextCheckpoint, ContextFrame, ContextTimeline
from grid_agent.trajectory.replay import ReplayEventLike


RULE_CONTEXT_FRAME = "context-frame/v1"
MISSING_REQUEST_INPUT = "legacy source did not capture model request input"
UNAVAILABLE_CONTEXT_ARTIFACT = "context artifact could not be verified"
UNAVAILABLE_NATIVE_CONTEXT = "native context state has no verified artifact"


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


def _verified_context_state(
    artifacts: object, reference: str, event: ReplayEventLike
) -> dict[str, Any] | None:
    verify_reference = getattr(artifacts, "verify_reference", None)
    verify = getattr(artifacts, "verify", None)
    if not callable(verify_reference) or not callable(verify):
        return None
    try:
        pointer = verify_reference(reference)
        if not isinstance(pointer, ArtifactPointer) or pointer.kind != "context-view":
            return None
        path = verify(pointer)
        if not isinstance(path, Path):
            return None
        document = json.loads(path.read_bytes())
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        return None
    if not isinstance(document, Mapping):
        return None
    if (
        document.get("analysis_id") != event.analysis_id
        or document.get("revision") != event.payload.get("revision")
        or document.get("state_hash") != event.payload.get("state_hash")
    ):
        return None
    return _copy_state(document)


def _after_state(
    state: Mapping[str, Any], event: ReplayEventLike, artifacts: object
) -> tuple[dict[str, Any], str | None]:
    payload = event.payload
    artifact_ref = payload.get("artifact_ref")
    if event.event_type in {"context.projected", "context.injected"} and isinstance(
        artifact_ref, str
    ):
        verified = _verified_context_state(artifacts, artifact_ref, event)
        if verified is not None:
            return verified, None
        return _copy_state(state), UNAVAILABLE_CONTEXT_ARTIFACT
    snapshot = payload.get("after_state", payload.get("context_state"))
    if isinstance(snapshot, Mapping):
        return _copy_state(snapshot), None
    if event.event_type in {"context.projected", "context.injected"}:
        return _copy_state(state), UNAVAILABLE_NATIVE_CONTEXT
    return _copy_state(state), None


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
    """Return immutable frames using only snapshots or verified context views."""
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
        after, context_unavailable_reason = _after_state(before, event, artifacts)
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
            status="unavailable" if context_unavailable_reason else "completed",
            unavailable_reason=(
                context_unavailable_reason
                if context_unavailable_reason
                else None if request_ref else MISSING_REQUEST_INPUT
            ),
        )
        frames.append(frame)
        state, revision = after, after_revision
        if event.sequence % checkpoint_interval == 0 or event.event_type in {"turn.completed", "analysis.completed"}:
            checkpoints.append(ContextCheckpoint(source_sequence=event.sequence, context_revision=revision, state_hash=frame.after_state_hash, state=state))
    return ContextTimeline(analysis_id=events[0].analysis_id, frames=tuple(frames), checkpoints=tuple(checkpoints))


__all__ = [
    "MISSING_REQUEST_INPUT",
    "RULE_CONTEXT_FRAME",
    "UNAVAILABLE_CONTEXT_ARTIFACT",
    "UNAVAILABLE_NATIVE_CONTEXT",
    "project_context",
]
