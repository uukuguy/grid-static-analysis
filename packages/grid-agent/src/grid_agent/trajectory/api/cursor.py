"""Opaque, signed cursors for immutable trajectory projection pages."""

from __future__ import annotations

import base64
import binascii
import hmac
import os
import secrets
import stat
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from grid_agent.trajectory.canonical import canonical_json_bytes
from grid_agent.trajectory.events import StrictFrozenModel


_FILTER_BOUND_VIEWS = frozenset({"agent", "context", "evidence"})


class CursorError(ValueError):
    """A cursor cannot be safely used for the requested projection page."""


class CursorState(StrictFrozenModel):
    """The complete signed position of an older-than projection page."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    analysis_id: str = Field(min_length=1)
    view: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=1)
    projection_version: str = Field(min_length=1)
    before_sequence: int = Field(ge=1)
    direction: Literal["older"] = "older"


class CursorExpectation(StrictFrozenModel):
    """The immutable source and filter identity a supplied cursor must match."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    analysis_id: str = Field(min_length=1)
    view: str = Field(min_length=1)
    source_fingerprint: str = Field(min_length=1)
    projection_version: str = Field(min_length=1)
    direction: Literal["older"] = "older"


class CursorCodec:
    """Encodes state with an operator-local HMAC key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("cursor key must contain 32 bytes")
        self._key = key

    @classmethod
    def load_or_create(cls, key_path: Path) -> "CursorCodec":
        """Load a private key, creating it atomically if it has no owner yet."""
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            key = _read_private_key(key_path)
        else:
            key = secrets.token_bytes(32)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                try:
                    key_path.unlink(missing_ok=True)
                finally:
                    raise
        return cls(key)

    def encode(self, state: CursorState) -> str:
        body = canonical_json_bytes(state.model_dump(mode="json")).rstrip(b"\n")
        signature = hmac.digest(self._key, body, "sha256")
        return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")

    def decode(self, value: str, expected: CursorExpectation) -> CursorState:
        if not isinstance(value, str) or not value:
            raise CursorError("invalid cursor encoding")
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
            if len(decoded) <= 33 or decoded[-33] != ord("."):
                raise ValueError("cursor separator is missing")
            body, signature = decoded[:-33], decoded[-32:]
        except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
            raise CursorError("invalid cursor encoding") from exc
        if not hmac.compare_digest(signature, hmac.digest(self._key, body, "sha256")):
            raise CursorError("tampered cursor")
        try:
            state = CursorState.model_validate_json(body)
        except ValidationError as exc:
            raise CursorError("invalid cursor payload") from exc
        _validate_expected_cursor(state, expected)
        return state


def _validate_expected_cursor(state: CursorState, expected: CursorExpectation) -> None:
    if state.analysis_id != expected.analysis_id:
        raise CursorError("foreign run cursor")
    if state.view != expected.view:
        raise CursorError("wrong view cursor")
    if state.source_fingerprint != expected.source_fingerprint:
        if state.view in _FILTER_BOUND_VIEWS:
            state_source, state_filters = _split_filter_bound_fingerprint(
                state.source_fingerprint
            )
            expected_source, expected_filters = _split_filter_bound_fingerprint(
                expected.source_fingerprint
            )
            if (
                state_filters is not None
                and expected_filters is not None
                and state_source == expected_source
            ):
                raise CursorError("filter-mismatched cursor")
        raise CursorError("stale source cursor")
    if state.projection_version != expected.projection_version:
        raise CursorError("stale projection cursor")
    if state.direction != expected.direction:
        raise CursorError("wrong cursor direction")


def _split_filter_bound_fingerprint(value: str) -> tuple[str, str | None]:
    """Separate the final filter digest without misreading plain SHA-256 refs."""
    source, separator, filter_digest = value.rpartition(":")
    if (
        separator
        and len(filter_digest) == 64
        and all(character in "0123456789abcdef" for character in filter_digest)
    ):
        return source, filter_digest
    return value, None


def _read_private_key(key_path: Path) -> bytes:
    """Read an existing key only after verifying its secure filesystem identity."""
    try:
        path_status = os.lstat(key_path)
        if not stat.S_ISREG(path_status.st_mode):
            raise ValueError("cursor key must be a regular file")
        descriptor = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError("cursor key cannot be safely opened") from exc

    with os.fdopen(descriptor, "rb") as handle:
        key_status = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(key_status.st_mode)
            or (path_status.st_dev, path_status.st_ino)
            != (key_status.st_dev, key_status.st_ino)
        ):
            raise ValueError("cursor key must be a regular file")
        if key_status.st_mode & 0o077:
            raise ValueError("cursor key must be private")
        if key_status.st_uid != os.geteuid():
            raise ValueError("cursor key must be owned by the current user")
        if key_status.st_size != 32:
            raise ValueError("cursor key must contain 32 bytes")
        return handle.read()


__all__ = ["CursorCodec", "CursorError", "CursorExpectation", "CursorState"]
