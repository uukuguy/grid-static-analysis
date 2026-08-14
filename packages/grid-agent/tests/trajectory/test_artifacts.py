from __future__ import annotations

from pathlib import Path

import pytest

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
