from __future__ import annotations

import os
from pathlib import Path

import pytest

from grid_agent.trajectory.api.cursor import (
    CursorCodec,
    CursorError,
    CursorExpectation,
    CursorState,
)


def cursor_state() -> CursorState:
    return CursorState(
        analysis_id="analysis-test",
        view="business",
        source_fingerprint="sha256:source",
        projection_version="business-trajectory/1.0",
        before_sequence=800,
    )


def expected_cursor(**changes: str) -> CursorExpectation:
    state = cursor_state().model_dump()
    state.update(changes)
    state.pop("before_sequence")
    return CursorExpectation(**state)


def test_cursor_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")
    state = cursor_state()
    encoded = codec.encode(state)

    assert codec.decode(encoded, expected=expected_cursor()) == state
    replacement = "A" if encoded[-1] != "A" else "B"
    with pytest.raises(CursorError, match="tampered"):
        codec.decode(encoded[:-1] + replacement, expected=expected_cursor())


def test_cursor_key_is_private_and_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "cursor.key"
    first = CursorCodec.load_or_create(path)
    second = CursorCodec.load_or_create(path)

    assert first.encode(cursor_state()) == second.encode(cursor_state())
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_cursor_rejects_foreign_run_wrong_view_and_stale_projection(tmp_path: Path) -> None:
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")
    encoded = codec.encode(cursor_state())

    for field, value, message in (
        ("analysis_id", "analysis-other", "foreign run"),
        ("view", "agent", "wrong view"),
        ("source_fingerprint", "sha256:new", "stale source"),
        ("projection_version", "business-trajectory/2.0", "stale projection"),
    ):
        with pytest.raises(CursorError, match=message):
            codec.decode(encoded, expected=expected_cursor(**{field: value}))


def test_cursor_rejects_malformed_and_non_positive_boundaries(tmp_path: Path) -> None:
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")

    with pytest.raises(CursorError, match="invalid cursor encoding"):
        codec.decode("!", expected=expected_cursor())
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        CursorState(**(cursor_state().model_dump() | {"before_sequence": 0}))
