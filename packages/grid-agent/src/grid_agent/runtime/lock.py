from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grid_agent.application.paths import ProjectPaths


EXPECTED_SCHEMA_VERSION = 2
PATCH_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PiRuntimeLockError(ValueError):
    pass


@dataclass(frozen=True)
class PiRuntimeIdentity:
    path: Path
    source: str
    package_version: str
    lock_sha256: str
    pi_ai_version: str = ""
    patches_sha256: str = ""
    commit: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class PiRuntimePatch:
    path: Path
    sha256: str


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
    pi_ai_version: str
    pi_ai_npm_integrity: str
    patches: tuple[PiRuntimePatch, ...]
    patches_sha256: str
    sha256: str

    @classmethod
    def load(cls, path: Path | None = None) -> PiRuntimeLock:
        lock_path = (path or default_lock_path()).resolve()
        raw = lock_path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PiRuntimeLockError(f"Invalid Pi runtime lock JSON: {exc}") from exc

        cls._validate(data)
        package = data["package"]
        source = data["source"]
        runtime = data["runtime"]
        patches = cls._load_patches(lock_path, data.get("patches"))
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
            pi_ai_version=runtime["pi_ai_version"],
            pi_ai_npm_integrity=runtime["pi_ai_npm_integrity"],
            patches=patches,
            patches_sha256=cls._patches_sha256(lock_path, patches),
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
        required_runtime = {"node_minimum", "pi_ai_version", "pi_ai_npm_integrity"}
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
        if runtime["pi_ai_version"] != "0.80.6":
            raise PiRuntimeLockError("Pi runtime lock pi-ai version is not pinned to 0.80.6")
        if runtime["pi_ai_npm_integrity"] != "sha512-7xfLk8sANBp+bpPEbjoOZTbPxsa+++b1JXAoSJsNa3vbs9AHHEclmvg54XLQcxH+fuwaeti/g2jeIfJ+mVYLpA==":
            raise PiRuntimeLockError("Pi runtime lock pi-ai integrity is not pinned")
        if package["npm_integrity"] != "sha512-vcfD6tOk402isLl3Cm/qbn2O10TvgroMp1+/fEGM24ZdvETFCdOYv5VZ7m59EI5fPsjfSJh+CpQ5bhBrhfOg7g==":
            raise PiRuntimeLockError("Pi runtime lock package integrity is not the pinned value")

    @staticmethod
    def _load_patches(lock_path: Path, raw_patches: Any) -> tuple[PiRuntimePatch, ...]:
        if not isinstance(raw_patches, list) or not raw_patches:
            raise PiRuntimeLockError("Pi runtime lock patches must contain at least one patch entry")

        patches: list[PiRuntimePatch] = []
        config_dir = lock_path.parent.resolve()
        for raw_patch in raw_patches:
            if not isinstance(raw_patch, dict):
                raise PiRuntimeLockError("Pi runtime lock patch entry must be a JSON object")

            patch_path_value = raw_patch.get("path")
            patch_sha256 = raw_patch.get("sha256")
            if not isinstance(patch_path_value, str) or not patch_path_value:
                raise PiRuntimeLockError("Pi runtime lock patch path must be a non-empty string")
            if not isinstance(patch_sha256, str) or PATCH_SHA256_RE.fullmatch(patch_sha256) is None:
                raise PiRuntimeLockError("Pi runtime lock patch digest must be 64 lowercase hexadecimal characters")

            relative_path = Path(patch_path_value)
            if relative_path.is_absolute():
                raise PiRuntimeLockError("Pi runtime lock patch path must be relative")
            if ".." in relative_path.parts:
                raise PiRuntimeLockError("Pi runtime lock patch path escapes runtime config directory")

            patch_path = (config_dir / relative_path).resolve()
            try:
                patch_path.relative_to(config_dir)
            except ValueError as exc:
                raise PiRuntimeLockError("Pi runtime lock patch path escapes runtime config directory") from exc

            try:
                actual_sha256 = hashlib.sha256(patch_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise PiRuntimeLockError(f"Pi runtime lock patch file cannot be read: {patch_path}") from exc
            if actual_sha256 != patch_sha256:
                raise PiRuntimeLockError(
                    f"Pi runtime lock patch digest mismatch for {patch_path}: expected {patch_sha256}, got {actual_sha256}"
                )
            patches.append(PiRuntimePatch(path=patch_path, sha256=patch_sha256))

        return tuple(patches)

    @staticmethod
    def _patches_sha256(lock_path: Path, patches: tuple[PiRuntimePatch, ...]) -> str:
        config_dir = lock_path.parent.resolve()
        payload = json.dumps(
            [
                {
                    "path": patch.path.relative_to(config_dir).as_posix(),
                    "sha256": patch.sha256,
                }
                for patch in patches
            ],
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def default_lock_path() -> Path:
    return ProjectPaths.from_root(Path(__file__).resolve().parents[5]).runtime_lock
