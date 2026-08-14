"""Immutable, digest-verified sidecar artifacts for trajectory events."""

from __future__ import annotations

import os
import re
import secrets
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from grid_agent.trajectory.canonical import canonical_json_bytes


IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
KIND_LAYOUT: dict[str, tuple[str, str]] = {
    "request-input": ("requests/{identity}", "input.json"),
    "model-response": ("requests/{identity}", "response.json"),
    "answer": ("turns/{identity}", "answer.json"),
}


class ArtifactIntegrityError(RuntimeError):
    """Raised when an artifact cannot safely be admitted or verified."""


@dataclass(frozen=True, slots=True)
class ArtifactPointer:
    """Content-addressed metadata for one immutable run artifact."""

    ref: str
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int


class ImmutableArtifactRegistry:
    """Write and admit only safe, immutable artifacts rooted in one run."""

    def __init__(self, run_root: Path) -> None:
        requested_root = Path(run_root).absolute()
        if _contains_symlink(requested_root):
            raise ArtifactIntegrityError("artifact run root must not be a symlink")
        self.run_root = requested_root.resolve(strict=False)

    def write_json(self, kind: str, identity: str, payload: object) -> ArtifactPointer:
        """Atomically write canonical JSON once, returning a verified pointer."""
        path = self._path_for(kind, identity)
        value = canonical_json_bytes(payload)
        self._ensure_parent(path, create=True)

        existing = self._read_if_regular(path)
        if existing is None:
            published = _write_bytes_atomic(path, value)
            if not published:
                existing = self._read_if_regular(path)
        if existing is not None and existing != value:
            raise ArtifactIntegrityError(
                "artifact path already contains different content"
            )

        return self._pointer_for(kind, identity, path, value)

    def register_existing(
        self, kind: str, identity: str, path: Path
    ) -> ArtifactPointer:
        """Admit an existing, regular artifact without changing any byte."""
        expected = self._path_for(kind, identity)
        supplied = Path(path).absolute()
        if supplied != expected:
            raise ArtifactIntegrityError(
                "artifact path is not the registered path for its kind and identity"
            )
        self._ensure_parent(expected, create=False)
        value = self._read_if_regular(expected)
        if value is None:
            raise ArtifactIntegrityError("registered artifact does not exist")
        return self._pointer_for(kind, identity, expected, value)

    def verify(self, pointer: ArtifactPointer) -> Path:
        """Verify *pointer* still identifies a regular, unchanged sidecar."""
        identity = self._identity_from_pointer(pointer)
        path = self._path_for(pointer.kind, identity)
        if path.relative_to(self.run_root).as_posix() != pointer.relative_path:
            raise ArtifactIntegrityError("artifact pointer has an invalid relative path")
        if (
            not isinstance(pointer.size_bytes, int)
            or isinstance(pointer.size_bytes, bool)
            or pointer.size_bytes < 0
        ):
            raise ArtifactIntegrityError("artifact pointer has an invalid size")
        if not isinstance(pointer.sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", pointer.sha256
        ):
            raise ArtifactIntegrityError("artifact pointer has an invalid digest")
        if pointer.ref != f"artifact:sha256:{pointer.sha256}":
            raise ArtifactIntegrityError("artifact pointer has an invalid reference")

        self._ensure_parent(path, create=False)
        value = self._read_if_regular(path)
        if value is None:
            raise ArtifactIntegrityError("artifact does not exist")
        if len(value) != pointer.size_bytes:
            raise ArtifactIntegrityError("artifact size does not match its pointer")
        if sha256(value).hexdigest() != pointer.sha256:
            raise ArtifactIntegrityError("artifact digest does not match its pointer")
        return path

    def _path_for(self, kind: str, identity: str) -> Path:
        if not isinstance(kind, str) or kind not in KIND_LAYOUT:
            raise ArtifactIntegrityError("artifact kind is not registered")
        if not isinstance(identity, str) or not IDENTITY_PATTERN.fullmatch(identity):
            raise ArtifactIntegrityError("artifact identity is invalid")
        directory, filename = KIND_LAYOUT[kind]
        return self.run_root / directory.format(identity=identity) / filename

    def _pointer_for(
        self, kind: str, identity: str, path: Path, value: bytes
    ) -> ArtifactPointer:
        digest = sha256(value).hexdigest()
        pointer = ArtifactPointer(
            ref=f"artifact:sha256:{digest}",
            kind=kind,
            relative_path=path.relative_to(self.run_root).as_posix(),
            sha256=digest,
            size_bytes=len(value),
        )
        self.verify(pointer)
        return pointer

    def _identity_from_pointer(self, pointer: ArtifactPointer) -> str:
        if (
            not isinstance(pointer.kind, str)
            or pointer.kind not in KIND_LAYOUT
            or not isinstance(pointer.relative_path, str)
        ):
            raise ArtifactIntegrityError("artifact pointer has an invalid kind or path")
        directory, filename = KIND_LAYOUT[pointer.kind]
        prefix, marker, suffix = directory.partition("{identity}")
        if not marker:
            raise ArtifactIntegrityError("artifact kind has no identity layout")
        relative = PurePosixPath(pointer.relative_path)
        expected_prefix = PurePosixPath(prefix).parts
        expected_suffix = PurePosixPath(suffix).parts
        parts = relative.parts
        expected_length = len(expected_prefix) + 1 + len(expected_suffix) + 1
        if (
            relative.is_absolute()
            or len(parts) != expected_length
            or parts[: len(expected_prefix)] != expected_prefix
            or parts[-1] != filename
        ):
            raise ArtifactIntegrityError("artifact pointer has an invalid relative path")
        identity_index = len(expected_prefix)
        if parts[identity_index + 1 : -1] != expected_suffix:
            raise ArtifactIntegrityError("artifact pointer has an invalid relative path")
        identity = parts[identity_index]
        if not IDENTITY_PATTERN.fullmatch(identity):
            raise ArtifactIntegrityError("artifact pointer has an invalid identity")
        return identity

    def _ensure_parent(self, path: Path, *, create: bool) -> None:
        self._ensure_run_root(create=create)
        try:
            relative = path.relative_to(self.run_root)
        except ValueError as error:
            raise ArtifactIntegrityError("artifact path escapes the run root") from error

        current = self.run_root
        for component in relative.parts[:-1]:
            current = current / component
            details = _lstat(current)
            if details is None:
                if not create:
                    raise ArtifactIntegrityError("registered artifact directory does not exist")
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                details = _lstat(current)
            if details is None or stat.S_ISLNK(details.st_mode):
                raise ArtifactIntegrityError("artifact path traverses a symlink")
            if not stat.S_ISDIR(details.st_mode):
                raise ArtifactIntegrityError("artifact parent is not a directory")

        resolved_parent = path.parent.resolve(strict=True)
        if not _is_within(resolved_parent, self.run_root):
            raise ArtifactIntegrityError("artifact path escapes the real run root")

    def _ensure_run_root(self, *, create: bool) -> None:
        details = _lstat(self.run_root)
        if details is None:
            if not create:
                raise ArtifactIntegrityError("artifact run root does not exist")
            self.run_root.mkdir(parents=True, exist_ok=True)
            details = _lstat(self.run_root)
        if details is None or stat.S_ISLNK(details.st_mode):
            raise ArtifactIntegrityError("artifact run root must not be a symlink")
        if not stat.S_ISDIR(details.st_mode):
            raise ArtifactIntegrityError("artifact run root is not a directory")

    def _read_if_regular(self, path: Path) -> bytes | None:
        details = _lstat(path)
        if details is None:
            return None
        if stat.S_ISLNK(details.st_mode):
            raise ArtifactIntegrityError("artifact file must not be a symlink")
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactIntegrityError("artifact file is not regular")
        return path.read_bytes()


def _write_bytes_atomic(path: Path, value: bytes) -> bool:
    """Publish *value* with no replacement of an existing artifact."""
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return False
        _fsync_directory(path.parent)
        return True
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        details = _lstat(current)
        if details is not None and stat.S_ISLNK(details.st_mode):
            return True
    return False
