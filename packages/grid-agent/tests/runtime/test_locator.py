from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

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


def create_managed_runtime(state_dir: Path, runtime_lock: PiRuntimeLock) -> Path:
    source = state_dir / "var/runtime/pi/source"
    cli = source / runtime_lock.executable
    helper = source / runtime_lock.oauth_helper
    cli.parent.mkdir(parents=True, exist_ok=True)
    helper.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    helper.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    return source


def test_locator_marks_explicit_command_unmanaged(tmp_path: Path) -> None:
    command = PiRuntimeLocator(tmp_path, {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"}).resolve()
    assert command.argv == ("/opt/homebrew/bin/pi",)
    assert command.identity.source == "explicit_override"


def test_locator_does_not_search_ambient_pi_or_research_checkouts(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)

    command = PiRuntimeLocator(
        tmp_path,
        {"PATH": "/tmp/path-with-pi", "PI_HOME": "/tmp/ambient-pi", "GRID_AGENT_PI_SOURCE": "3th" + "-party/pi"},
    ).resolve()

    assert command.identity.source == "managed"
    assert command.path == tmp_path / "var/runtime/pi/source" / runtime_lock.executable


def test_locator_records_managed_identity_and_lock_sha(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)

    command = PiRuntimeLocator(tmp_path, {}).resolve()

    assert command.argv == ("node", str(tmp_path / "var/runtime/pi/source" / runtime_lock.executable))
    assert command.identity.source == "managed"
    assert command.identity.commit == runtime_lock.commit
    assert command.identity.lock_sha256 == runtime_lock.sha256
    assert command.identity.package_version == "0.80.6"


def test_locator_resolves_managed_oauth_helper(tmp_path: Path, runtime_lock: PiRuntimeLock) -> None:
    create_managed_runtime(tmp_path, runtime_lock)

    helper = PiRuntimeLocator(tmp_path, {}).resolve_oauth_helper()

    assert helper.argv == ("node", str(tmp_path / "var/runtime/pi/source" / runtime_lock.oauth_helper))
    assert helper.identity.source == "managed"
    assert helper.identity.commit == runtime_lock.commit


def test_locator_resolves_explicit_oauth_helper_from_sibling_package(tmp_path: Path) -> None:
    command = tmp_path / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    helper_path = tmp_path / "node_modules/@earendil-works/pi-ai/dist/cli.js"
    command.parent.mkdir(parents=True)
    helper_path.parent.mkdir(parents=True)
    command.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    helper_path.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    helper = PiRuntimeLocator(tmp_path, {"GRID_AGENT_PI_COMMAND": str(command)}).resolve_oauth_helper()

    assert helper.argv == ("node", str(helper_path))
    assert helper.identity.source == "explicit_override"


def test_locator_fails_clearly_when_explicit_oauth_helper_is_missing(tmp_path: Path) -> None:
    command = tmp_path / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    command.parent.mkdir(parents=True)
    command.write_text("#!/usr/bin/env node\n", encoding="utf-8")

    with pytest.raises(PiRuntimeLocatorError, match="pi-ai"):
        PiRuntimeLocator(tmp_path, {"GRID_AGENT_PI_COMMAND": str(command)}).resolve_oauth_helper()


def test_probe_runs_non_generation_version_check(tmp_path: Path) -> None:
    runner = FakeRunner()

    probed = PiRuntimeLocator(
        tmp_path,
        {"GRID_AGENT_PI_COMMAND": "/opt/homebrew/bin/pi"},
        runner=runner,
    ).probe()

    assert probed.version == "0.80.6"
    assert runner.calls == [["/opt/homebrew/bin/pi", "--version"]]
    assert runner.kwargs[0]["shell"] is False
    assert runner.kwargs[0]["capture_output"] is True
