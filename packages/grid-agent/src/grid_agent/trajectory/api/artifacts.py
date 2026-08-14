"""Allowlisted, digest-verified access to trajectory artifacts."""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from grid_agent.trajectory.projection_models import ArtifactIndex


_MEDIA_TYPES = {
    ".json": "application/json; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


class ArtifactAccessError(RuntimeError):
    """Raised when an artifact cannot be safely served from a run."""


@dataclass(frozen=True, slots=True)
class ArtifactResponse:
    """A freshly verified artifact suitable for a fixed read-only response."""

    content: bytes
    media_type: str
    filename: str
    sha256: str
    size_bytes: int


class ArtifactGateway:
    """Resolve only indexed artifact references and reverify them on every open."""

    def __init__(self, run_root: Path, artifact_index: ArtifactIndex) -> None:
        self.run_root = Path(run_root)
        self.artifact_index = artifact_index

    def open(self, artifact_ref: str) -> ArtifactResponse:
        """Return a regular, in-run file whose current bytes match its index digest."""
        _validate_reference(artifact_ref)
        record = self.artifact_index.records.get(artifact_ref)
        if record is None:
            raise ArtifactAccessError("artifact is not registered")

        try:
            root = self.run_root.resolve(strict=True)
        except OSError as exc:
            raise ArtifactAccessError("artifact is not a safe run path") from exc
        if not root.is_dir():
            raise ArtifactAccessError("artifact is not a safe run path")

        relative_path = _safe_relative_path(record.relative_path)
        try:
            descriptor = _open_nofollow(root, relative_path)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ArtifactAccessError("artifact is not a safe run path") from exc
            raise ArtifactAccessError("artifact is not a regular file") from exc
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ArtifactAccessError("artifact is not a regular file")
            with os.fdopen(descriptor, "rb", closefd=True) as artifact_file:
                descriptor = -1
                value = artifact_file.read()
        except OSError as exc:
            raise ArtifactAccessError("artifact is not a regular file") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if file_stat.st_size != len(value):
            raise ArtifactAccessError("artifact integrity mismatch")
        if sha256(value).hexdigest() != record.sha256:
            raise ArtifactAccessError("artifact integrity mismatch")

        return ArtifactResponse(
            content=value,
            media_type=media_type_for(Path(relative_path.name)),
            filename=relative_path.name,
            sha256=record.sha256,
            size_bytes=len(value),
        )


def media_type_for(path: Path) -> str:
    """Return one of the fixed non-executable media types for an artifact file."""
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ArtifactAccessError("artifact media type is not allowed")
    return media_type


def _validate_reference(artifact_ref: str) -> None:
    if not isinstance(artifact_ref, str):
        raise ArtifactAccessError("invalid artifact reference")
    if "%2f" in artifact_ref.lower() or "%5c" in artifact_ref.lower():
        raise ArtifactAccessError("invalid artifact reference")


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value:
        raise ArtifactAccessError("artifact is not a safe run path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ArtifactAccessError("artifact is not a safe run path")
    return path


def _open_nofollow(root: Path, relative_path: PurePosixPath) -> int:
    """Open an indexed file through descriptor-relative no-follow traversal."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    try:
        for part in relative_path.parts[:-1]:
            next_directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        return os.open(relative_path.parts[-1], os.O_RDONLY | nofollow, dir_fd=directory)
    finally:
        os.close(directory)


__all__ = ["ArtifactAccessError", "ArtifactGateway", "ArtifactResponse", "media_type_for"]
