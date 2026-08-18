from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock


CODEX_PROVIDER = "openai-codex"


class AuthStoreError(ValueError):
    pass


@dataclass(frozen=True)
class AuthStatus:
    provider: str
    auth_kind: str
    configured: bool
    expiry: int | None = None


class ProjectAuthStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.grid-agent.lock")

    @classmethod
    def from_pi_agent_dir(cls, directory: Path) -> "ProjectAuthStore":
        return cls(Path(directory) / "auth.json")

    def import_provider(self, source: Path, provider: str) -> AuthStatus:
        self._require_codex(provider)
        source = Path(source)
        if source.is_symlink():
            raise AuthStoreError("OAuth source must not be a symlink")
        data = self._read_json(source, missing_ok=False)
        entry = self._validated_entry(data, provider)
        with self._lock():
            self._write_data({provider: entry})
        return self.status(provider)

    def status(self, provider: str) -> AuthStatus:
        self._require_codex(provider)
        with self._lock():
            data = self._read_json(self.path, missing_ok=True)
            entry = data.get(provider)
            if entry is None:
                return AuthStatus(provider=provider, auth_kind="oauth", configured=False)
            entry = self._validated_entry(data, provider)
            expiry = entry.get("expiry")
            return AuthStatus(
                provider=provider,
                auth_kind="oauth",
                configured=True,
                expiry=expiry if isinstance(expiry, int) else None,
            )

    def logout(self, provider: str) -> AuthStatus:
        self._require_codex(provider)
        with self._lock():
            data = self._read_json(self.path, missing_ok=True)
            if provider in data:
                del data[provider]
                self._write_data(data)
        return self.status(provider)

    def read_redacted(self) -> dict[str, dict[str, object]]:
        status = self.status(CODEX_PROVIDER)
        if not status.configured:
            return {}
        result: dict[str, object] = {"type": status.auth_kind, "configured": True}
        if status.expiry is not None:
            result["expiry"] = status.expiry
        return {CODEX_PROVIDER: result}

    def ensure_secure_directory(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        return self.path.parent

    def _lock(self) -> FileLock:
        self.ensure_secure_directory()
        return FileLock(str(self.lock_path))

    def _write_data(self, data: dict[str, Any]) -> None:
        directory = self.ensure_secure_directory()
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=directory)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _read_json(path: Path, *, missing_ok: bool) -> dict[str, Any]:
        if not path.exists():
            if missing_ok:
                return {}
            raise AuthStoreError("OAuth source does not exist")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthStoreError("OAuth credentials are not valid JSON") from exc
        if not isinstance(data, dict):
            raise AuthStoreError("OAuth credentials must be a JSON object")
        return data

    @staticmethod
    def _validated_entry(data: dict[str, Any], provider: str) -> dict[str, Any]:
        entry = data.get(provider)
        if not isinstance(entry, dict) or entry.get("type") != "oauth":
            raise AuthStoreError("Project OAuth entry is missing or invalid")
        return entry

    @staticmethod
    def _require_codex(provider: str) -> None:
        if provider != CODEX_PROVIDER:
            raise AuthStoreError("Only openai-codex OAuth is supported")
