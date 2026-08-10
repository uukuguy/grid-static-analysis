from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED_SCHEMA_VERSION = 1


class PiRuntimeLockError(ValueError):
    pass


@dataclass(frozen=True)
class PiRuntimeIdentity:
    path: Path
    source: str
    package_version: str
    lock_sha256: str
    commit: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class PiCommand:
    argv: tuple[str, ...]
    identity: PiRuntimeIdentity

    @property
    def path(self) -> Path:
        return self.identity.path

    @property
    def version(self) -> str | None:
        return self.identity.version


@dataclass(frozen=True)
class PiOAuthHelper:
    argv: tuple[str, ...]
    identity: PiRuntimeIdentity

    @property
    def path(self) -> Path:
        return self.identity.path


@dataclass(frozen=True)
class PiRuntimeLock:
    path: Path
    repository: str
    commit: str
    package_name: str
    package_version: str
    package_directory: Path
    package_executable: Path
    oauth_helper: Path
    npm_integrity: str
    node_minimum: str
    sha256: str

    @classmethod
    def load(cls, path: Path | None = None) -> PiRuntimeLock:
        lock_path = path or default_lock_path()
        raw = lock_path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PiRuntimeLockError(f"Invalid Pi runtime lock JSON: {exc}") from exc

        cls._validate(data)
        package = data["package"]
        source = data["source"]
        runtime = data["runtime"]
        return cls(
            path=lock_path,
            repository=source["repository"],
            commit=source["commit"],
            package_name=package["name"],
            package_version=package["version"],
            package_directory=Path(package["directory"]),
            package_executable=Path(package["executable"]),
            oauth_helper=Path(package["oauth_helper"]),
            npm_integrity=package["npm_integrity"],
            node_minimum=runtime["node_minimum"],
            sha256=hashlib.sha256(raw).hexdigest(),
        )

    @property
    def version(self) -> str:
        return self.package_version

    @property
    def executable(self) -> Path:
        return self.package_directory / self.package_executable

    @staticmethod
    def _validate(data: Any) -> None:
        if not isinstance(data, dict):
            raise PiRuntimeLockError("Pi runtime lock must be a JSON object")
        if data.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            raise PiRuntimeLockError("Unsupported Pi runtime lock schema version")

        source = data.get("source")
        package = data.get("package")
        runtime = data.get("runtime")
        if not isinstance(source, dict) or not isinstance(package, dict) or not isinstance(runtime, dict):
            raise PiRuntimeLockError("Pi runtime lock is missing source, package, or runtime sections")

        required_source = {"repository", "commit"}
        required_package = {"name", "version", "directory", "executable", "oauth_helper", "npm_integrity"}
        required_runtime = {"node_minimum"}
        missing = required_source - source.keys() or required_package - package.keys() or required_runtime - runtime.keys()
        if missing:
            raise PiRuntimeLockError(f"Pi runtime lock missing required fields: {', '.join(sorted(missing))}")

        if source["repository"] != "https://github.com/earendil-works/pi.git":
            raise PiRuntimeLockError("Pi runtime lock repository is not the pinned Pi repository")
        if source["commit"] != "2b3fda9921b5590f285165287bd442a25817f17b":
            raise PiRuntimeLockError("Pi runtime lock commit is not the pinned Pi commit")
        if package["name"] != "@earendil-works/pi-coding-agent":
            raise PiRuntimeLockError("Pi runtime lock package name is not the pinned Pi package")
        if package["version"] != "0.80.6":
            raise PiRuntimeLockError("Pi runtime lock package version is not pinned to 0.80.6")
        if package["npm_integrity"] != "sha512-vcfD6tOk402isLl3Cm/qbn2O10TvgroMp1+/fEGM24ZdvETFCdOYv5VZ7m59EI5fPsjfSJh+CpQ5bhBrhfOg7g==":
            raise PiRuntimeLockError("Pi runtime lock package integrity is not the pinned value")


def default_lock_path() -> Path:
    return Path(__file__).resolve().parents[5] / "runtime/pi-runtime.lock.json"
