"""Bidirectional immutable-artifact lineage projection."""

from __future__ import annotations

from collections.abc import Sequence
from grid_agent.trajectory.artifacts import ArtifactPointer
from grid_agent.trajectory.projection_models import ArtifactIndex, ArtifactIndexRecord
from grid_agent.trajectory.replay import ReplayEventLike


def _pointer(registry: object, reference: str) -> ArtifactPointer | None:
    verify = getattr(registry, "verify_reference", None)
    if callable(verify):
        try:
            value = verify(reference)
        except Exception:  # Missing/tampered historical sidecars are projected, not fatal.
            return None
        return value if isinstance(value, ArtifactPointer) else None
    return None


def project_artifacts(events: Sequence[ReplayEventLike], registry: object) -> ArtifactIndex:
    if not events:
        return ArtifactIndex(analysis_id="unknown")
    produced: dict[str, ReplayEventLike] = {}
    consumed: dict[str, list[ReplayEventLike]] = {}
    for event in events:
        for reference in event.refs.produced:
            produced.setdefault(reference, event)
        for reference in (*event.refs.consumed, *event.refs.evidence):
            consumed.setdefault(reference, []).append(event)
    records: dict[str, ArtifactIndexRecord] = {}
    for reference in sorted(set(produced) | set(consumed)):
        producer = produced.get(reference)
        consumers = consumed.get(reference, [])
        pointer = _pointer(registry, reference)
        sequences = tuple(sorted({event.sequence for event in ([producer] if producer else []) + consumers}))
        if not sequences:
            continue
        scope = producer.scope if producer else consumers[0].scope
        records[reference] = ArtifactIndexRecord(
            id=f"artifact:{events[0].analysis_id}:{reference}", source_sequences=sequences,
            reference=reference, kind=pointer.kind if pointer else "unavailable",
            relative_path=pointer.relative_path if pointer else "unavailable",
            sha256=pointer.sha256 if pointer else "unavailable",
            verification_status="verified" if pointer else "unavailable",
            status="completed" if pointer else "unavailable",
            unavailable_reason=None if pointer else "artifact reference could not be verified",
            producing_sequence=producer.sequence if producer else None,
            consuming_sequences=tuple(sorted({event.sequence for event in consumers})),
            turn_id=scope.turn_id, step_id=scope.step_id, request_id=scope.request_id,
            tool_call_id=scope.tool_call_id,
        )
    return ArtifactIndex(analysis_id=events[0].analysis_id, records=records)


__all__ = ["project_artifacts"]
