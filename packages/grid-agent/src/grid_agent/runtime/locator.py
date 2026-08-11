from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from grid_agent.runtime.lock import PiCommand, PiOAuthHelper, PiRuntimeIdentity, PiRuntimeLock


ENV_PI_COMMAND = "GRID_AGENT_PI_COMMAND"
Runner = Callable[..., subprocess.CompletedProcess[str]]


class PiRuntimeLocatorError(RuntimeError):
    pass


class PiRuntimeLocator:
    def __init__(
        self,
        state_dir: Path,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_lock: PiRuntimeLock | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.environ = dict(environ or {})
        self.runtime_lock = runtime_lock or PiRuntimeLock.load()
        self.runner = runner or subprocess.run

    @classmethod
    def from_cwd(cls) -> PiRuntimeLocator:
        return cls(Path.cwd(), os.environ)

    @property
    def source_dir(self) -> Path:
        return self.state_dir / "var/runtime/pi/source"

    def resolve(self) -> PiCommand:
        explicit = self.environ.get(ENV_PI_COMMAND)
        if explicit:
            path = Path(explicit)
            identity = self._identity(path=path, source="explicit_override", commit=None)
            return PiCommand(argv=(str(path),), identity=identity)

        cli = self.source_dir / self.runtime_lock.executable
        if cli.is_file():
            identity = self._identity(path=cli, source="managed", commit=self.runtime_lock.commit)
            return PiCommand(argv=("node", str(cli)), identity=identity)

        path_command = shutil.which("pi", path=self.environ.get("PATH", ""))
        if path_command:
            path = Path(path_command)
            identity = self._identity(path=path, source="path", commit=None)
            return PiCommand(argv=(str(path),), identity=identity)

        raise PiRuntimeLocatorError(
            "No Pi runtime is available; add pi to PATH, set GRID_AGENT_PI_COMMAND, or install the managed runtime"
        )

    def resolve_oauth_helper(self) -> PiOAuthHelper:
        explicit = self.environ.get(ENV_PI_COMMAND)
        if explicit:
            command_path = Path(explicit)
            helper = self._explicit_helper_path(command_path)
            if not helper.is_file():
                raise PiRuntimeLocatorError(
                    "Pinned Pi OAuth helper @earendil-works/pi-ai is unavailable next to explicit GRID_AGENT_PI_COMMAND"
                )
            identity = self._identity(path=helper, source="explicit_override", commit=None)
            return PiOAuthHelper(argv=("node", str(helper)), identity=identity)

        helper = self.source_dir / self.runtime_lock.oauth_helper
        if not helper.is_file():
            raise PiRuntimeLocatorError(f"Managed Pi OAuth helper is missing: {helper}")
        identity = self._identity(path=helper, source="managed", commit=self.runtime_lock.commit)
        return PiOAuthHelper(argv=("node", str(helper)), identity=identity)

    def probe(self) -> PiCommand:
        command = self.resolve()
        result = self._run([*command.argv, "--version"])
        version = _parse_version(result.stdout)
        if version != self.runtime_lock.package_version:
            raise PiRuntimeLocatorError(
                f"Pi runtime version mismatch: expected {self.runtime_lock.package_version}, got {version}"
            )
        return PiCommand(
            argv=command.argv,
            identity=replace(command.identity, version=version),
        )

    def _identity(self, *, path: Path, source: str, commit: str | None) -> PiRuntimeIdentity:
        return PiRuntimeIdentity(
            path=path,
            source=source,
            commit=commit,
            package_version=self.runtime_lock.package_version,
            lock_sha256=self.runtime_lock.sha256,
        )

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        try:
            result = self.runner(
                command,
                cwd=self.state_dir,
                timeout=15,
                shell=False,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PiRuntimeLocatorError(f"Pi runtime command failed to start: {command!r}: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            message = f"Pi runtime command failed ({' '.join(command)})"
            if detail:
                message = f"{message}: {detail}"
            raise PiRuntimeLocatorError(message)
        return result

    @staticmethod
    def _explicit_helper_path(command_path: Path) -> Path:
        for parent in command_path.parents:
            if parent.name == "node_modules":
                return parent / "@earendil-works/pi-ai/dist/cli.js"
        return command_path.parent / "node_modules/@earendil-works/pi-ai/dist/cli.js"


def _parse_version(stdout: str) -> str:
    for line in stdout.splitlines():
        value = line.strip()
        if value:
            return value.removeprefix("v")
    raise PiRuntimeLocatorError("Pi runtime version probe returned no version")
