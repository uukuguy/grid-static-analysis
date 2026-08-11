from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint(serialized_network: str) -> str:
    return hashlib.sha256(serialized_network.encode("utf-8")).hexdigest()


def write_network(path: Path, serialized_network: str) -> None:
    path.write_text(serialized_network, encoding="utf-8")


def write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
