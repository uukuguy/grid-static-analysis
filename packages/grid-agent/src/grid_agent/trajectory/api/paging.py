"""Record- and byte-bounded tail-first projection paging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from grid_agent.trajectory.api.cursor import CursorState
from grid_agent.trajectory.canonical import canonical_json_bytes


MAX_PAGE_RECORDS = 500
MAX_PAGE_BYTES = 2 * 1024 * 1024


class SequenceRecord(Protocol):
    """A projection item with a stable source sequence boundary."""

    sequence: int

    def model_dump(self, *, mode: str) -> object: ...


RecordT = TypeVar("RecordT", bound=SequenceRecord)


class ProjectionRecordTooLarge(ValueError):
    """One record cannot fit in the immutable page-size budget."""


@dataclass(frozen=True)
class ProjectionPage(Generic[RecordT]):
    """One ascending sequence slice, reached from the newest source records."""

    items: tuple[RecordT, ...]
    older_cursor: int | None
    newer_cursor: None
    first_sequence: int | None
    last_sequence: int | None
    has_older: bool
    encoded_bytes: int


class ProjectionPager:
    """Build bounded pages without trusting client-controlled sequence bounds."""

    def page(
        self,
        records: tuple[RecordT, ...],
        *,
        cursor_state: CursorState | None = None,
        max_records: int = MAX_PAGE_RECORDS,
        max_bytes: int = MAX_PAGE_BYTES,
    ) -> ProjectionPage:
        if not 1 <= max_records <= MAX_PAGE_RECORDS:
            raise ValueError(f"max_records must be between 1 and {MAX_PAGE_RECORDS}")
        if not 1 <= max_bytes <= MAX_PAGE_BYTES:
            raise ValueError(f"max_bytes must be between 1 and {MAX_PAGE_BYTES}")

        ordered = tuple(sorted(records, key=lambda record: record.sequence))
        _validate_records(ordered)
        before_sequence = cursor_state.before_sequence if cursor_state else None
        available = tuple(
            record
            for record in ordered
            if before_sequence is None or record.sequence < before_sequence
        )
        selected: list[RecordT] = []
        encoded_bytes = 0
        for record in reversed(available):
            record_bytes = len(canonical_json_bytes(record.model_dump(mode="json")))
            if record_bytes > max_bytes:
                raise ProjectionRecordTooLarge("projection record exceeds byte budget")
            if len(selected) == max_records or encoded_bytes + record_bytes > max_bytes:
                break
            selected.append(record)
            encoded_bytes += record_bytes
        selected.reverse()

        has_older = len(selected) < len(available)
        first_sequence = selected[0].sequence if selected else None
        last_sequence = selected[-1].sequence if selected else None
        # The page layer owns only sequence arithmetic.  The HTTP boundary adds
        # its immutable run/view identity and signs this boundary opaquely.
        older_cursor = first_sequence if has_older else None
        return ProjectionPage(
            items=tuple(selected),
            older_cursor=older_cursor,
            newer_cursor=None,
            first_sequence=first_sequence,
            last_sequence=last_sequence,
            has_older=has_older,
            encoded_bytes=encoded_bytes,
        )


def _validate_records(records: tuple[SequenceRecord, ...]) -> None:
    previous = 0
    for record in records:
        if not isinstance(record.sequence, int) or isinstance(record.sequence, bool) or record.sequence < 1:
            raise ValueError("projection record sequence must be a positive integer")
        if record.sequence <= previous:
            raise ValueError("projection record sequences must be unique")
        previous = record.sequence


__all__ = [
    "MAX_PAGE_BYTES",
    "MAX_PAGE_RECORDS",
    "ProjectionPage",
    "ProjectionPager",
    "ProjectionRecordTooLarge",
    "SequenceRecord",
]
