from __future__ import annotations

from pydantic import BaseModel
import pytest

from grid_agent.trajectory.api.cursor import CursorState
from grid_agent.trajectory.api.paging import ProjectionPager, ProjectionRecordTooLarge


class PageRecord(BaseModel):
    sequence: int
    payload: str


def page_record(sequence: int, payload: str = "x") -> PageRecord:
    return PageRecord(sequence=sequence, payload=payload)


def test_page_enforces_record_and_byte_limits_from_the_tail() -> None:
    records = tuple(page_record(sequence, payload="x" * 20_000) for sequence in range(1, 1001))

    page = ProjectionPager().page(records)

    assert len(page.items) <= 500
    assert page.encoded_bytes <= 2 * 1024 * 1024
    assert page.items[-1].sequence == 1000
    assert page.has_older is True
    assert page.older_cursor == page.items[0].sequence
    assert page.newer_cursor is None


def test_page_uses_signed_cursor_boundary_and_prepends_older_records() -> None:
    records = tuple(page_record(sequence) for sequence in range(1, 8))
    pager = ProjectionPager()
    first = pager.page(records, max_records=3)
    cursor = CursorState(
        analysis_id="analysis-test",
        view="business",
        source_fingerprint="sha256:source",
        projection_version="business-trajectory/1.0",
        before_sequence=first.older_cursor,  # type: ignore[arg-type]
    )

    second = pager.page(records, cursor_state=cursor, max_records=3)

    assert [item.sequence for item in first.items] == [5, 6, 7]
    assert [item.sequence for item in second.items] == [2, 3, 4]
    assert second.first_sequence == 2
    assert second.last_sequence == 4
    assert second.has_older is True


def test_page_rejects_a_single_record_larger_than_the_byte_budget() -> None:
    with pytest.raises(ProjectionRecordTooLarge, match="byte budget"):
        ProjectionPager().page((page_record(1, payload="x" * 100),), max_bytes=20)
