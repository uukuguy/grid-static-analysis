"""Immutable, digest-verified sidecar artifacts for trajectory events."""

from __future__ import annotations

import errno
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Iterator, NoReturn

from grid_agent.trajectory.canonical import canonical_json_bytes


IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
KIND_LAYOUT: dict[str, tuple[str, str]] = {
    "request-input": ("requests/{identity}", "input.json"),
    "model-response": ("requests/{identity}", "response.json"),
    "answer": ("turns/{identity}", "answer.json"),
}
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


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
        self.run_root = Path(os.path.abspath(run_root))
        _validate_directory_prefix(self.run_root)

    def write_json(self, kind: str, identity: str, payload: object) -> ArtifactPointer:
        """Atomically write canonical JSON once, returning a verified pointer."""
        path = self._path_for(kind, identity)
        value = canonical_json_bytes(payload)
        with self._open_parent(path, create=True) as (_, parent_descriptor):
            existing = _read_regular_at(parent_descriptor, path.name)
            if existing is None:
                published = _write_bytes_atomic(parent_descriptor, path.name, value)
                if not published:
                    existing = _read_regular_at(parent_descriptor, path.name)
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
        with self._open_parent(expected, create=False) as (_, parent_descriptor):
            value = _read_regular_at(parent_descriptor, expected.name)
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

        with self._open_parent(path, create=False) as (
            root_descriptor,
            parent_descriptor,
        ):
            artifact_descriptor = _open_regular_at(parent_descriptor, path.name)
            if artifact_descriptor is None:
                raise ArtifactIntegrityError("artifact does not exist")
            try:
                value = _read_descriptor(artifact_descriptor)
                if len(value) != pointer.size_bytes:
                    raise ArtifactIntegrityError(
                        "artifact size does not match its pointer"
                    )
                if sha256(value).hexdigest() != pointer.sha256:
                    raise ArtifactIntegrityError(
                        "artifact digest does not match its pointer"
                    )
                self._verify_named_binding(
                    path,
                    root_descriptor=root_descriptor,
                    parent_descriptor=parent_descriptor,
                    artifact_descriptor=artifact_descriptor,
                )
            finally:
                os.close(artifact_descriptor)
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

    @contextmanager
    def _open_parent(
        self, path: Path, *, create: bool
    ) -> Iterator[tuple[int, int]]:
        try:
            relative = path.relative_to(self.run_root)
        except ValueError as error:
            raise ArtifactIntegrityError("artifact path escapes the run root") from error
        root_descriptor = _open_directory_path(self.run_root, create=create)
        parent_descriptor: int | None = None
        try:
            parent_descriptor = _open_relative_directory(
                root_descriptor, relative.parts[:-1], create=create
            )
            yield root_descriptor, parent_descriptor
        finally:
            if parent_descriptor is not None:
                os.close(parent_descriptor)
            os.close(root_descriptor)

    def _verify_named_binding(
        self,
        path: Path,
        *,
        root_descriptor: int,
        parent_descriptor: int,
        artifact_descriptor: int,
    ) -> None:
        """Ensure the verified descriptors are still named by the returned path."""
        relative = path.relative_to(self.run_root)
        rebound_root = _open_directory_path(self.run_root, create=False)
        rebound_parent: int | None = None
        try:
            if not _same_file_descriptor(rebound_root, root_descriptor):
                raise ArtifactIntegrityError("artifact run root changed during verification")
            rebound_parent = _open_relative_directory(
                rebound_root, relative.parts[:-1], create=False
            )
            if not _same_file_descriptor(rebound_parent, parent_descriptor):
                raise ArtifactIntegrityError("artifact parent changed during verification")
            rebound_artifact = _open_regular_at(rebound_parent, path.name)
            if rebound_artifact is None:
                raise ArtifactIntegrityError("artifact changed during verification")
            try:
                if not _same_file_descriptor(rebound_artifact, artifact_descriptor):
                    raise ArtifactIntegrityError("artifact changed during verification")
            finally:
                os.close(rebound_artifact)
        finally:
            if rebound_parent is not None:
                os.close(rebound_parent)
            os.close(rebound_root)


def _write_bytes_atomic(parent_descriptor: int, filename: str, value: bytes) -> bool:
    """Publish *value* with no replacement of an existing artifact."""
    temporary = f".{filename}.{secrets.token_hex(8)}.tmp"
    temporary_descriptor: int | None = None
    try:
        temporary_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o666,
            dir_fd=parent_descriptor,
        )
        _write_descriptor(temporary_descriptor, value)
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = None
        try:
            os.link(
                temporary,
                filename,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            return False
        os.fsync(parent_descriptor)
        return True
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass


def _validate_directory_prefix(path: Path) -> None:
    """Reject symlinks/non-directories in the existing prefix of *path*."""
    descriptor = _open_anchor(path)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                return
            except OSError as error:
                _raise_directory_error(error)
            os.close(descriptor)
            descriptor = child
    finally:
        os.close(descriptor)


def _open_directory_path(path: Path, *, create: bool) -> int:
    descriptor = _open_anchor(path)
    try:
        for component in path.parts[1:]:
            child = _open_child_directory(descriptor, component, create=create)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_anchor(path: Path) -> int:
    try:
        return os.open(path.anchor, _DIRECTORY_OPEN_FLAGS)
    except OSError as error:
        _raise_directory_error(error)


def _open_relative_directory(
    root_descriptor: int, components: tuple[str, ...], *, create: bool
) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for component in components:
            child = _open_child_directory(descriptor, component, create=create)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_child_directory(
    parent_descriptor: int, component: str, *, create: bool
) -> int:
    try:
        return os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
    except FileNotFoundError as missing:
        if not create:
            raise ArtifactIntegrityError(
                "registered artifact directory does not exist"
            ) from missing
        try:
            os.mkdir(component, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        try:
            return os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
        except OSError as error:
            _raise_directory_error(error)
    except OSError as error:
        _raise_directory_error(error)


def _open_regular_at(parent_descriptor: int, filename: str) -> int | None:
    try:
        descriptor = os.open(filename, _FILE_OPEN_FLAGS, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise ArtifactIntegrityError("artifact file must not be a symlink") from error
        raise ArtifactIntegrityError("artifact file could not be opened safely") from error

    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        os.close(descriptor)
        raise ArtifactIntegrityError("artifact file is not regular")
    return descriptor


def _read_regular_at(parent_descriptor: int, filename: str) -> bytes | None:
    descriptor = _open_regular_at(parent_descriptor, filename)
    if descriptor is None:
        return None
    try:
        return _read_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _write_descriptor(descriptor: int, value: bytes) -> None:
    remaining = memoryview(value)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise ArtifactIntegrityError("artifact temporary write made no progress")
        remaining = remaining[written:]


def _same_file_descriptor(left: int, right: int) -> bool:
    left_details = os.fstat(left)
    right_details = os.fstat(right)
    return (left_details.st_dev, left_details.st_ino) == (
        right_details.st_dev,
        right_details.st_ino,
    )


def _raise_directory_error(error: OSError) -> NoReturn:
    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise ArtifactIntegrityError(
            "artifact path traverses a symlink or non-directory"
        ) from error
    raise ArtifactIntegrityError("artifact directory could not be opened safely") from error
