from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.locator import PiRuntimeLocator, PiRuntimeLocatorError
from grid_agent.runtime.lock import PiRuntimeLock


@pytest.fixture
def runtime_lock() -> PiRuntimeLock:
    return PiRuntimeLock.load()


class FakeRunner:
    def __init__(self, *, version: str = "0.80.6") -> None:
        self.version = version
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        return subprocess.CompletedProcess(list(argv), 0, self.version + "\n", "")


def write_active_marker(state_dir: Path, runtime_lock: PiRuntimeLock, source: Path, **overrides: str) -> Path:
    marker = ProjectPaths.from_root(state_dir).pi_runtime_dir / "active"
    marker.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "commit": runtime_lock.commit,
        "lock_sha256": runtime_lock.sha256,
        "patches_sha256": runtime_lock.patches_sha256,
        **overrides,
    }
    marker.write_text(
        f"{source}\n"
        f"commit={values['commit']}\n"
        f"lock_sha256={values['lock_sha256']}\n"
        f"patches_sha256={values['patches_sha256']}\n",
        encoding="utf-8",
    )
    return marker


def create_managed_runtime(state_dir: Path, runtime_lock: PiRuntimeLock, *, active_marker: bool = True) -> Path:
    paths = ProjectPaths.from_root(state_dir)
    source = paths.pi_runtime_dir / "source"
    cli = source / runtime_lock.executable
    helper = source / runtime_lock.oauth_helper
    cli.parent.mkdir(parents=True, exist_ok=True)
    helper.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    helper.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    if active_marker:
        write_active_marker(state_dir, runtime_lock, source)
    return source


def test_locator_marks_explicit_command_unmanaged(tmp_path: Path) -> None:
    command = PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"}).resolve()
    assert command.argv == ("/opt/homebrew/bin/pi",)
    assert command.identity.source == "explicit_override"


def test_locator_requires_verified_managed_runtime_for_native_capture(tmp_path: Path) -> None:
    locator = PiRuntimeLocator(
        ProjectPaths.from_root(tmp_path).pi_runtime_dir,
        {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"},
    )

    with pytest.raises(PiRuntimeLocatorError, match="active marker"):
        locator.resolve(require_managed=True)


def test_locator_prefers_managed_runtime_over_path_pi(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)
    paths = ProjectPaths.from_root(tmp_path)

    command = PiRuntimeLocator(
        paths.pi_runtime_dir,
        {"PATH": "/tmp/path-with-pi", "PI_HOME": "/tmp/ambient-pi", "GRID_AGENT_PI_SOURCE": "3th" + "-party/pi"},
    ).resolve()

    assert command.identity.source == "managed"
    assert command.path == paths.pi_runtime_dir / "source" / runtime_lock.executable


def test_locator_falls_back_to_path_when_managed_executable_has_no_active_marker(
    tmp_path: Path,
    runtime_lock: PiRuntimeLock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_managed_runtime(tmp_path, runtime_lock, active_marker=False)
    monkeypatch.setattr("grid_agent.runtime.locator.shutil.which", lambda *_args, **_kwargs: "/opt/homebrew/bin/pi")

    command = PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"PATH": "/opt/homebrew/bin"}).resolve()

    assert command.argv == ("/opt/homebrew/bin/pi",)
    assert command.identity.source == "path"


@pytest.mark.parametrize(
    "marker_text",
    [
        "not enough\n",
        "/tmp/other/source\ncommit=2b3fda9921b5590f285165287bd442a25817f17b\nlock_sha256=lock\npatches_sha256=patches\n",
        None,
    ],
)
def test_locator_rejects_invalid_managed_active_marker(
    tmp_path: Path,
    runtime_lock: PiRuntimeLock,
    monkeypatch: pytest.MonkeyPatch,
    marker_text: str | None,
) -> None:
    source = create_managed_runtime(tmp_path, runtime_lock)
    marker = ProjectPaths.from_root(tmp_path).pi_runtime_dir / "active"
    if marker_text is None:
        write_active_marker(tmp_path, runtime_lock, source, lock_sha256="0" * 64)
    else:
        marker.write_text(marker_text, encoding="utf-8")
    monkeypatch.setattr("grid_agent.runtime.locator.shutil.which", lambda *_args, **_kwargs: "/opt/homebrew/bin/pi")

    with pytest.raises(PiRuntimeLocatorError, match="active marker"):
        PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"PATH": "/opt/homebrew/bin"}).resolve()


def test_locator_uses_pi_from_path_when_no_explicit_or_managed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("grid_agent.runtime.locator.shutil.which", lambda *_args, **_kwargs: "/opt/homebrew/bin/pi")

    command = PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"PATH": "/opt/homebrew/bin"}).resolve()

    assert command.argv == ("/opt/homebrew/bin/pi",)
    assert command.identity.source == "path"


def test_locator_records_managed_identity_and_lock_sha(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)
    paths = ProjectPaths.from_root(tmp_path)

    command = PiRuntimeLocator(paths.pi_runtime_dir, {}).resolve()

    assert command.argv == ("node", str(paths.pi_runtime_dir / "source" / runtime_lock.executable))
    assert command.identity.source == "managed"
    assert command.identity.commit == runtime_lock.commit
    assert command.identity.lock_sha256 == runtime_lock.sha256
    assert command.identity.package_version == "0.80.6"
    assert command.identity.pi_ai_version == "0.80.6"
    assert command.identity.patches_sha256 == runtime_lock.patches_sha256


def test_locator_resolves_managed_oauth_helper(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)
    paths = ProjectPaths.from_root(tmp_path)

    helper = PiRuntimeLocator(paths.pi_runtime_dir, {}).resolve_oauth_helper()

    assert helper.argv == ("node", str(paths.pi_runtime_dir / "source" / runtime_lock.oauth_helper))
    assert helper.identity.source == "managed"
    assert helper.identity.commit == runtime_lock.commit


def test_locator_resolves_explicit_oauth_helper_from_sibling_package(tmp_path: Path) -> None:
    command = tmp_path / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    helper_path = tmp_path / "node_modules/@earendil-works/pi-ai/dist/cli.js"
    command.parent.mkdir(parents=True)
    helper_path.parent.mkdir(parents=True)
    command.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    helper_path.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    helper = PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"GRID_AGENT_PI_COMMAND": str(command)}).resolve_oauth_helper()

    assert helper.argv == ("node", str(helper_path))
    assert helper.identity.source == "explicit_override"


def test_locator_fails_clearly_when_explicit_oauth_helper_is_missing(tmp_path: Path) -> None:
    command = tmp_path / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    command.parent.mkdir(parents=True)
    command.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    with pytest.raises(PiRuntimeLocatorError, match="pi-ai"):
        PiRuntimeLocator(ProjectPaths.from_root(tmp_path).pi_runtime_dir, {"GRID_AGENT_PI_COMMAND": str(command)}).resolve_oauth_helper()


def test_probe_runs_non_generation_version_check(tmp_path: Path) -> None:
    runner = FakeRunner()

    probed = PiRuntimeLocator(
        ProjectPaths.from_root(tmp_path).pi_runtime_dir,
        {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"},
        runner=runner,
    ).probe()

    assert probed.version == "0.80.6"
    assert runner.calls == [["/opt/homebrew/bin/pi", "--version"]]
    assert runner.kwargs[0]["shell"] is False
    assert runner.kwargs[0]["capture_output"] is True
