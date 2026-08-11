from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint(serialized_network: str) -> str:
    return hashlib.sha256(serialized_network.encode("utf-8")).hexdigest()


def write_network(path: Path, serialized_network: str) -> None:
    path.write_text(serialized_network, encoding="utf-8")
