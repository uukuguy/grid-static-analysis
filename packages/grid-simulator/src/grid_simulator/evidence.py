from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def fingerprint(payload: str | bytes) -> str:
    return hashlib.sha256(_as_bytes(payload)).hexdigest()


def canonical_json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_network(path: Path, serialized_network: str) -> None:
    write_text_atomic(path, serialized_network)


def write_json(path: Path, document: object) -> None:
    write_text_atomic(path, canonical_json(document))


def write_text_atomic(path: Path, text: str) -> None:
    write_bytes_atomic(path, text.encode("utf-8"))


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, path)


def _as_bytes(payload: str | bytes) -> bytes:
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return payload
