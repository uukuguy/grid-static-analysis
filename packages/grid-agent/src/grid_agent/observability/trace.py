import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


class JsonlTraceWriter:
    def __init__(self, path: Path, *, secret_values: set[str] | None = None) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_values = frozenset(value for value in (secret_values or set()) if value)
        self._sequence = self._read_existing_sequence(path)
        self._stream: TextIO = path.open("a", encoding="utf-8")

    def append(self, event: str, payload: Any) -> None:
        self._sequence += 1
        record = {
            "sequence": self._sequence,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "event": event,
            "payload": self._redact(payload),
        }
        self._stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            redacted = value
            for secret in self._secret_values:
                redacted = redacted.replace(secret, "[REDACTED]")
            return redacted
        if isinstance(value, Mapping):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [self._redact(item) for item in value]
        return value

    @staticmethod
    def _read_existing_sequence(path: Path) -> int:
        if not path.exists():
            return 0

        last_sequence = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            sequence = record.get("sequence")
            if isinstance(sequence, int):
                last_sequence = sequence
        return last_sequence
