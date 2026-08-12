from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.installer import PiRuntimeInstaller, PiRuntimeInstallerError
from grid_agent.runtime.lock import PiRuntimeLock


@pytest.fixture
def runtime_lock() -> PiRuntimeLock:
    return PiRuntimeLock.load()


class FakeRunner:
    def __init__(self, *, version: str = "0.80.6", fail_build: bool = False) -> None:
        self.version = version
        self.fail_build = fail_build
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        cwd = Path(kwargs["cwd"])
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


def test_installer_uses_detached_pinned_commit(tmp_path: Path, fake_runner: FakeRunner, runtime_lock: PiRuntimeLock) -> None:
    command = PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=fake_runner).install()
    assert ["git", "fetch", "--depth", "1", "origin", runtime_lock.commit] in fake_runner.calls
    assert ["git", "checkout", "--detach", runtime_lock.commit] in fake_runner.calls
    assert ["npm", "ci"] in fake_runner.calls
    assert ["npm", "run", "build"] in fake_runner.calls
    assert command.identity.commit == "2b3fda9921b5590f285165287bd442a25817f17b"


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


def test_installer_rejects_version_mismatch(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    with pytest.raises(PiRuntimeInstallerError, match="0.80.6"):
        PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=FakeRunner(version="0.80.5")).install()


def test_failed_build_never_becomes_active(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    with pytest.raises(PiRuntimeInstallerError, match="npm run build"):
        PiRuntimeInstaller(runtime_lock, ProjectPaths.from_root(tmp_path).pi_runtime_dir, runner=FakeRunner(fail_build=True)).install()

    active = tmp_path / ".grid-agent/runtime/pi/active"
    assert not active.exists()
