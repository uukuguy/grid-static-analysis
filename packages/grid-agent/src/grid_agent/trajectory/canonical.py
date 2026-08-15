"""Canonical JSON serialization and SHA-256 reference helpers."""

from __future__ import annotations

import json
from hashlib import sha256


def canonical_json_bytes(value: object) -> bytes:
    """Serialize *value* as canonical UTF-8 JSON with one final newline."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_ref(value: bytes) -> str:
    """Return the lowercase SHA-256 reference for *value*."""
    return f"sha256:{sha256(value).hexdigest()}"
