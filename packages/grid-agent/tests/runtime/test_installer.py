from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.installer import PiRuntimeInstaller, PiRuntimeInstallerError
from grid_agent.runtime.locator import PiRuntimeLocator, PiRuntimeLocatorError
from grid_agent.runtime.lock import PiRuntimeLock, PiRuntimeLockError


PATCH_RELATIVE_PATH = "patches/pi-0.80.6-before-model-request.patch"
PATCH_SHA256 = "458794796163d70c71846a4f38a543bf2ed495547c5fd216b2f1e0d684e1da0e"


def expected_patches_sha256(*patches: tuple[str, str]) -> str:
    payload = json.dumps(
        [{"path": path, "sha256": sha256} for path, sha256 in patches],
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def runtime_lock() -> PiRuntimeLock:
    return PiRuntimeLock.load()


class FakeRunner:
    def __init__(
        self,
        *,
        version: str = "0.80.6",
        fail_build: bool = False,
        fail_patch_check: bool = False,
        fail_patch_apply: bool = False,
    ) -> None:
        self.version = version
        self.fail_build = fail_build
        self.fail_patch_check = fail_patch_check
        self.fail_patch_apply = fail_patch_apply
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        cwd = Path(kwargs["cwd"])
        if list(argv)[:3] == ["git", "apply", "--check"] and self.fail_patch_check:
            return subprocess.CompletedProcess(list(argv), 1, "", "patch does not apply")
        if list(argv)[:2] == ["git", "apply"] and self.fail_patch_apply:
            return subprocess.CompletedProcess(list(argv), 1, "", "patch apply exploded")
        if list(argv) == ["git", "clean", "-fdx"]:
            stale_cli = cwd / "packages/coding-agent/dist/cli.js"
            if stale_cli.exists():
                stale_cli.unlink()
        if list(argv) == ["npm", "run", "build"]:
            if self.fail_build:
                return subprocess.CompletedProcess(list(argv), 1, "", "build exploded")
            cli = cwd / "packages/coding-agent/dist/cli.js"
            cli.parent.mkdir(parents=True, exist_ok=True)
            cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        if list(argv)[0] == "node" and list(argv)[-1] == "--version":
            return subprocess.CompletedProcess(list(argv), 0, self.version + "\n", "")
        return subprocess.CompletedProcess(list(argv), 0, "", "")


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


def lock_data(*, patches: list[dict[str, str]] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 2,
        "source": {
            "repository": "https://github.com/earendil-works/pi.git",
            "commit": "2b3fda9921b5590f285165287bd442a25817f17b",
        },
        "package": {
            "name": "@earendil-works/pi-coding-agent",
            "version": "0.80.6",
            "directory": "packages/coding-agent",
            "executable": "dist/cli.js",
            "oauth_helper": "packages/ai/dist/cli.js",
            "npm_integrity": "sha512-vcfD6tOk402isLl3Cm/qbn2O10TvgroMp1+/fEGM24ZdvETFCdOYv5VZ7m59EI5fPsjfSJh+CpQ5bhBrhfOg7g==",
        },
        "runtime": {
            "node_minimum": "22.19.0",
            "pi_ai_version": "0.80.6",
        },
    }
    if patches is not None:
        data["patches"] = patches
    return data


def write_lock(root: Path, data: dict[str, Any], patch_bytes: bytes = b"diff --git a/a b/a\n") -> Path:
    patch = root / PATCH_RELATIVE_PATH
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_bytes(patch_bytes)
    lock_path = root / "pi-runtime.lock.json"
    lock_path.write_text(json.dumps(data), encoding="utf-8")
    return lock_path


def test_lock_records_schema_v2_pi_ai_version_and_verified_patch_identity(runtime_lock: PiRuntimeLock) -> None:
    assert runtime_lock.pi_ai_version == "0.80.6"
    assert len(runtime_lock.patches) == 1
    assert runtime_lock.patches[0].path == runtime_lock.path.parent / PATCH_RELATIVE_PATH
    assert runtime_lock.patches[0].sha256 == PATCH_SHA256
    assert runtime_lock.patches_sha256 == expected_patches_sha256((PATCH_RELATIVE_PATH, PATCH_SHA256))


@pytest.mark.parametrize(
    ("patches", "message"),
    [
        (None, "patches"),
        ([{"path": PATCH_RELATIVE_PATH, "sha256": "0" * 64}], "digest"),
        ([{"path": "/tmp/pi.patch", "sha256": PATCH_SHA256}], "relative"),
        ([{"path": "../pi.patch", "sha256": PATCH_SHA256}], "escapes"),
    ],
)
def test_lock_rejects_missing_tampered_or_unsafe_patch_declarations(
    tmp_path: Path,
    patches: list[dict[str, str]] | None,
    message: str,
) -> None:
    lock_path = write_lock(tmp_path, lock_data(patches=patches), b"patch bytes")

    with pytest.raises(PiRuntimeLockError, match=message):
        PiRuntimeLock.load(lock_path)


def test_installer_uses_detached_pinned_commit(tmp_path: Path, fake_runner: FakeRunner, runtime_lock: PiRuntimeLock) -> None:
    command = PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=fake_runner).install()
    assert ["git", "fetch", "--depth", "1", "origin", runtime_lock.commit] in fake_runner.calls
    assert ["git", "checkout", "--detach", runtime_lock.commit] in fake_runner.calls
    assert ["git", "reset", "--hard", runtime_lock.commit] in fake_runner.calls
    assert ["git", "clean", "-fdx"] in fake_runner.calls
    assert ["git", "apply", "--check", str(runtime_lock.patches[0].path)] in fake_runner.calls
    assert ["git", "apply", str(runtime_lock.patches[0].path)] in fake_runner.calls
    assert ["npm", "ci"] in fake_runner.calls
    assert ["npm", "run", "build"] in fake_runner.calls
    assert fake_runner.calls.index(["git", "checkout", "--detach", runtime_lock.commit]) < fake_runner.calls.index(
        ["git", "reset", "--hard", runtime_lock.commit]
    )
    assert fake_runner.calls.index(["git", "reset", "--hard", runtime_lock.commit]) < fake_runner.calls.index(
        ["git", "clean", "-fdx"]
    )
    assert fake_runner.calls.index(["git", "clean", "-fdx"]) < fake_runner.calls.index(
        ["git", "apply", "--check", str(runtime_lock.patches[0].path)]
    )
    assert fake_runner.calls.index(["git", "apply", str(runtime_lock.patches[0].path)]) < fake_runner.calls.index(["npm", "ci"])
    assert command.identity.commit == "2b3fda9921b5590f285165287bd442a25817f17b"
    assert command.identity.pi_ai_version == "0.80.6"
    assert command.identity.patches_sha256 == runtime_lock.patches_sha256


def test_installer_uses_arrays_cwd_timeouts_and_captured_stderr(
    tmp_path: Path,
    fake_runner: FakeRunner,
    runtime_lock: PiRuntimeLock,
) -> None:
    PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=fake_runner).install()

    source = tmp_path / ".grid-agent/runtime/pi/source"
    assert source.is_dir()
    assert all(isinstance(call, list) for call in fake_runner.calls)
    assert all(kwargs["cwd"] == source for kwargs in fake_runner.kwargs)
    assert all(kwargs["shell"] is False for kwargs in fake_runner.kwargs)
    assert all(kwargs["capture_output"] is True for kwargs in fake_runner.kwargs)
    assert all(isinstance(kwargs["timeout"], int | float) and kwargs["timeout"] > 0 for kwargs in fake_runner.kwargs)


def test_installer_rejects_symlink_source_before_runner_or_marker_mutation(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    paths = ProjectPaths.from_root(tmp_path)
    outside = tmp_path / "outside-source"
    outside.mkdir()
    paths.pi_runtime_dir.mkdir(parents=True)
    paths.pi_runtime_dir.joinpath("source").symlink_to(outside, target_is_directory=True)
    active = paths.pi_runtime_dir / "active"
    active.write_text("stale marker\n", encoding="utf-8")
    runner = FakeRunner()

    with pytest.raises(PiRuntimeInstallerError, match="source"):
        PiRuntimeInstaller(runtime_lock, paths.pi_runtime_dir, runner=runner).install()

    assert runner.calls == []
    assert active.read_text(encoding="utf-8") == "stale marker\n"
    assert outside.exists()


def test_installer_rejects_symlink_runtime_root_before_runner_or_marker_mutation(
    tmp_path: Path,
    runtime_lock: PiRuntimeLock,
) -> None:
    paths = ProjectPaths.from_root(tmp_path)
    outside_root = tmp_path / "outside-runtime"
    outside_root.mkdir()
    outside_data = outside_root / "source" / "keep.txt"
    outside_data.parent.mkdir()
    outside_data.write_text("keep", encoding="utf-8")
    outside_marker = outside_root / "active"
    outside_marker.write_text("stale marker\n", encoding="utf-8")
    paths.pi_runtime_dir.parent.mkdir(parents=True)
    paths.pi_runtime_dir.symlink_to(outside_root, target_is_directory=True)
    runner = FakeRunner()

    with pytest.raises(PiRuntimeInstallerError, match="runtime root"):
        PiRuntimeInstaller(runtime_lock, paths.pi_runtime_dir, runner=runner).install()

    assert runner.calls == []
    assert outside_marker.read_text(encoding="utf-8") == "stale marker\n"
    assert outside_data.read_text(encoding="utf-8") == "keep"


def test_installer_normal_managed_source_proceeds_after_validation(
    tmp_path: Path,
    fake_runner: FakeRunner,
    runtime_lock: PiRuntimeLock,
) -> None:
    paths = ProjectPaths.from_root(tmp_path)
    paths.pi_runtime_dir.joinpath("source").mkdir(parents=True)

    PiRuntimeInstaller(runtime_lock, paths.pi_runtime_dir, runner=fake_runner).install()

    assert fake_runner.calls[0] == ["git", "init"]


def test_installer_rehashes_patch_bytes_before_running_git(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    patch = runtime_lock.patches[0].path
    lock_root = tmp_path / "runtime"
    lock_path = write_lock(
        lock_root,
        lock_data(patches=[{"path": PATCH_RELATIVE_PATH, "sha256": runtime_lock.patches[0].sha256}]),
        patch.read_bytes(),
    )
    local_lock = PiRuntimeLock.load(lock_path)
    local_lock.patches[0].path.write_text("tampered", encoding="utf-8")
    runner = FakeRunner()

    with pytest.raises(PiRuntimeInstallerError, match="digest"):
        PiRuntimeInstaller(local_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=runner).install()

    assert runner.calls == []
    assert not (tmp_path / ".grid-agent/runtime/pi/active").exists()


def test_installer_rejects_version_mismatch(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    with pytest.raises(PiRuntimeInstallerError, match="0.80.6"):
        PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=FakeRunner(version="0.80.5")).install()


@pytest.mark.parametrize("runner", [FakeRunner(fail_patch_check=True), FakeRunner(fail_patch_apply=True)])
def test_failed_patch_application_never_becomes_active(
    tmp_path: Path,
    runtime_lock: PiRuntimeLock,
    runner: FakeRunner,
) -> None:
    with pytest.raises(PiRuntimeInstallerError, match="git apply"):
        PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=runner).install()

    assert not (tmp_path / ".grid-agent/runtime/pi/active").exists()
    assert ["npm", "ci"] not in runner.calls


def test_failed_build_never_becomes_active(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    with pytest.raises(PiRuntimeInstallerError, match="npm run build"):
        PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=FakeRunner(fail_build=True)).install()

    active = tmp_path / ".grid-agent/runtime/pi/active"
    assert not active.exists()


def test_failed_build_removes_stale_marker_and_ignored_cli_output(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    paths = ProjectPaths.from_root(tmp_path)
    source = paths.pi_runtime_dir / "source"
    stale_cli = source / runtime_lock.executable
    stale_cli.parent.mkdir(parents=True, exist_ok=True)
    stale_cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    paths.pi_runtime_dir.mkdir(parents=True, exist_ok=True)
    (paths.pi_runtime_dir / "active").write_text(
        f"{source}\n"
        f"commit={runtime_lock.commit}\n"
        f"lock_sha256={runtime_lock.sha256}\n"
        f"patches_sha256={runtime_lock.patches_sha256}\n",
        encoding="utf-8",
    )

    with pytest.raises(PiRuntimeInstallerError, match="npm run build"):
        PiRuntimeInstaller(runtime_lock, paths.pi_runtime_dir, runner=FakeRunner(fail_build=True)).install()

    assert not (paths.pi_runtime_dir / "active").exists()
    assert not stale_cli.exists()
    with pytest.raises(PiRuntimeLocatorError):
        PiRuntimeLocator(paths.pi_runtime_dir, {}).resolve()


def test_active_marker_records_lock_and_patch_identity(
    tmp_path: Path,
    runtime_lock: PiRuntimeLock,
    fake_runner: FakeRunner,
) -> None:
    PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=fake_runner).install()

    active = tmp_path / ".grid-agent/runtime/pi/active"
    assert active.read_text(encoding="utf-8").splitlines() == [
        str(tmp_path / ".grid-agent/runtime/pi/source"),
        f"commit={runtime_lock.commit}",
        f"lock_sha256={runtime_lock.sha256}",
        f"patches_sha256={runtime_lock.patches_sha256}",
    ]
