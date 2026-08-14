from __future__ import annotations

import os
from pathlib import Path

import pytest

import grid_agent.trajectory.artifacts as artifact_module
from grid_agent.trajectory.artifacts import (
    ArtifactIntegrityError,
    ImmutableArtifactRegistry,
)


def test_registry_writes_once_and_verifies_digest(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "runs/analysis-test")
    pointer = registry.write_json(
        "request-input", "analysis-test-t001-r001", {"messages": [], "tools": []}
    )

    assert pointer.relative_path == "requests/analysis-test-t001-r001/input.json"
    assert pointer.ref == f"artifact:sha256:{pointer.sha256}"
    assert registry.verify(pointer).read_text(encoding="utf-8").endswith("\n")
    assert (
        registry.write_json(
            "request-input", "analysis-test-t001-r001", {"messages": [], "tools": []}
        )
        == pointer
    )


def test_registry_fsyncs_each_parent_before_opening_new_nested_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    calls: list[str] = []
    created_by_parent: dict[int, str] = {}
    real_fsync = os.fsync
    real_mkdir = os.mkdir
    real_open = os.open

    def recording_mkdir(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        real_mkdir(path, mode, dir_fd=dir_fd)
        assert dir_fd is not None
        component = os.fsdecode(path)
        created_by_parent[dir_fd] = component
        calls.append(f"mkdir:{component}")

    def recording_fsync(descriptor: int) -> None:
        if component := created_by_parent.get(descriptor):
            calls.append(f"fsync-parent:{component}")
        real_fsync(descriptor)

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        component = created_by_parent.get(dir_fd) if dir_fd is not None else None
        if component == os.fsdecode(path):
            calls.append(f"open-child:{component}")
            del created_by_parent[dir_fd]
        return descriptor

    monkeypatch.setattr(artifact_module.os, "mkdir", recording_mkdir)
    monkeypatch.setattr(artifact_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(artifact_module.os, "open", recording_open)

    pointer = registry.write_json("request-input", "request-1", {"messages": []})

    assert pointer.relative_path == "requests/request-1/input.json"
    assert calls == [
        "mkdir:run",
        "fsync-parent:run",
        "open-child:run",
        "mkdir:requests",
        "fsync-parent:requests",
        "open-child:requests",
        "mkdir:request-1",
        "fsync-parent:request-1",
        "open-child:request-1",
    ]


def test_registry_rejects_overwrite_with_different_content(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    registry.write_json("request-input", "request-1", {"messages": []})

    with pytest.raises(ArtifactIntegrityError, match="different content"):
        registry.write_json(
            "request-input", "request-1", {"messages": [{"role": "user"}]}
        )


def test_registry_registers_exact_preexisting_bytes(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    path = tmp_path / "run/requests/request-1/input.json"
    path.parent.mkdir(parents=True)
    value = b'{"provider_payload":{"messages":[]}}\n'
    path.write_bytes(value)

    pointer = registry.register_existing("request-input", "request-1", path)

    assert registry.verify(pointer).read_bytes() == value


@pytest.mark.parametrize(
    ("kind", "identity", "relative_path"),
    [
        (
            "result",
            "result:sha256:" + "a" * 64,
            "evidence/results/powerflow-" + "a" * 64 + ".json",
        ),
        (
            "evidence",
            "evidence:sha256:" + "b" * 64,
            "evidence/network-facts/network-fact-" + "b" * 64 + ".json",
        ),
        (
            "tool-result",
            "analysis-test-t001:call_1",
            "tool-results/analysis-test-t001/call_1.json",
        ),
        (
            "context-view",
            "r7-" + "c" * 64,
            "context/views/r7-" + "c" * 64 + "/view.json",
        ),
    ],
)
def test_registry_registers_current_run_artifact_kinds_without_rewriting(
    tmp_path: Path, kind: str, identity: str, relative_path: str
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    path = run_root / relative_path
    path.parent.mkdir(parents=True)
    value = b'{"preserve":"exact bytes"}\n'
    path.write_bytes(value)

    pointer = registry.register_existing(kind, identity, path)

    assert pointer.relative_path == relative_path
    assert registry.verify(pointer).read_bytes() == value
    assert registry.verify_reference(pointer.ref) == pointer


@pytest.mark.parametrize(
    ("kind", "identity", "relative_path"),
    [
        (
            "result",
            "result:sha256:" + "a" * 64,
            "evidence/analysis/powerflow-" + "a" * 64 + ".json",
        ),
        (
            "evidence",
            "evidence:sha256:" + "b" * 64,
            "evidence/results/network-fact-" + "b" * 64 + ".json",
        ),
        (
            "tool-result",
            "analysis-test-t001:call_1",
            "tool-results/analysis-test-t002/call_1.json",
        ),
    ],
)
def test_registry_rejects_new_artifact_kinds_outside_registered_layout(
    tmp_path: Path, kind: str, identity: str, relative_path: str
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    path = run_root / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}\n")

    with pytest.raises(ArtifactIntegrityError, match="registered path"):
        registry.register_existing(kind, identity, path)


@pytest.mark.parametrize(
    ("kind", "identity", "relative_path", "symlink_component"),
    [
        (
            "result",
            "result:sha256:" + "a" * 64,
            "evidence/results/powerflow-" + "a" * 64 + ".json",
            "evidence",
        ),
        (
            "evidence",
            "evidence:sha256:" + "b" * 64,
            "evidence/network-facts/network-fact-" + "b" * 64 + ".json",
            "evidence",
        ),
        (
            "tool-result",
            "analysis-test-t001:call_1",
            "tool-results/analysis-test-t001/call_1.json",
            "tool-results",
        ),
    ],
)
def test_registry_rejects_symlinked_new_artifact_kind_directories(
    tmp_path: Path,
    kind: str,
    identity: str,
    relative_path: str,
    symlink_component: str,
) -> None:
    run_root = tmp_path / "run"
    outside = tmp_path / "outside"
    run_root.mkdir()
    outside_path = outside / Path(relative_path).relative_to(symlink_component)
    outside_path.parent.mkdir(parents=True)
    outside_path.write_bytes(b"{}\n")
    (run_root / symlink_component).symlink_to(outside, target_is_directory=True)
    registry = ImmutableArtifactRegistry(run_root)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        registry.register_existing(kind, identity, run_root / relative_path)


@pytest.mark.parametrize("identity", ["../escape", "/absolute", "a/b", "a\\b"])
def test_registry_rejects_unsafe_identity(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ArtifactIntegrityError, match="identity"):
        ImmutableArtifactRegistry(tmp_path / "run").write_json("request-input", identity, {})


def test_registry_rejects_non_string_kind_and_identity(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")

    with pytest.raises(ArtifactIntegrityError, match="kind"):
        registry.write_json(1, "request-1", {})  # type: ignore[arg-type]
    with pytest.raises(ArtifactIntegrityError, match="identity"):
        registry.write_json("request-input", 1, {})  # type: ignore[arg-type]


def test_registry_rejects_tampered_artifact(tmp_path: Path) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    pointer = registry.write_json("request-input", "request-1", {"messages": []})
    path = tmp_path / "run" / pointer.relative_path
    path.write_text('{"messagex":[]}\n', encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="digest"):
        registry.verify(pointer)


def test_registry_rejects_symlinked_artifact_directory(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    run_root.mkdir()
    (run_root / "requests").symlink_to(outside, target_is_directory=True)
    registry = ImmutableArtifactRegistry(run_root)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        registry.write_json("request-input", "request-1", {"messages": []})


def test_registry_rejects_run_root_beneath_a_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        ImmutableArtifactRegistry(linked_root / "run")


def test_registry_rejects_existing_path_outside_its_registered_layout(
    tmp_path: Path,
) -> None:
    registry = ImmutableArtifactRegistry(tmp_path / "run")
    path = tmp_path / "run/requests/request-1/response.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"{}\n")

    with pytest.raises(ArtifactIntegrityError, match="registered path"):
        registry.register_existing("request-input", "request-1", path)


@pytest.mark.parametrize("replacement", ["parent", "file"])
def test_registry_rejects_replacement_during_verified_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    run_root = tmp_path / "run"
    registry = ImmutableArtifactRegistry(run_root)
    pointer = registry.write_json("request-input", "request-1", {"messages": []})
    artifact = run_root / pointer.relative_path
    artifact_parent = artifact.parent

    outside_parent = tmp_path / "outside" / "request-1"
    outside_parent.mkdir(parents=True)
    outside_artifact = outside_parent / artifact.name
    outside_artifact.write_bytes(artifact.read_bytes())

    original_read_bytes = Path.read_bytes
    original_open = os.open
    attacked = False

    def replace_checked_path() -> None:
        nonlocal attacked
        if attacked:
            return
        attacked = True
        if replacement == "parent":
            artifact_parent.rename(artifact_parent.with_name("request-1-original"))
            artifact_parent.symlink_to(outside_parent, target_is_directory=True)
        else:
            artifact.rename(artifact.with_name("input-original.json"))
            artifact.symlink_to(outside_artifact)

    def racing_read_bytes(path: Path) -> bytes:
        if path == artifact:
            replace_checked_path()
        return original_read_bytes(path)

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fsdecode(path) == artifact.name:
            replace_checked_path()
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)
    monkeypatch.setattr(artifact_module.os, "open", racing_open)

    with pytest.raises(ArtifactIntegrityError):
        registry.verify(pointer)
    assert attacked
