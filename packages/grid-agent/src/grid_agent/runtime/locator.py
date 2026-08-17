from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.lock import PiCommand, PiOAuthHelper, PiRuntimeIdentity, PiRuntimeLock


ENV_PI_COMMAND = "GRID_AGENT_PI_COMMAND"
Runner = Callable[..., subprocess.CompletedProcess[str]]


class PiRuntimeLocatorError(RuntimeError):
    pass


class PiRuntimeLocator:
    def __init__(
        self,
        pi_runtime_dir: Path,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_lock: PiRuntimeLock | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.pi_runtime_dir = Path(pi_runtime_dir)
        self.environ = dict(environ or {})
        self.runtime_lock = runtime_lock or PiRuntimeLock.load()
        self.runner = runner or subprocess.run

    @classmethod
    def from_cwd(cls) -> PiRuntimeLocator:
        return cls(ProjectPaths.from_root(Path.cwd()).pi_runtime_dir, os.environ)

    @property
    def source_dir(self) -> Path:
        return self.pi_runtime_dir / "source"

    @property
    def active_marker(self) -> Path:
        return self.pi_runtime_dir / "active"

    def resolve(self, *, require_managed: bool = False) -> PiCommand:
        if require_managed:
            cli = self.source_dir / self.runtime_lock.executable
            self._require_valid_active_marker()
            if not cli.is_file():
                raise PiRuntimeLocatorError(f"Managed Pi executable is missing: {cli}")
            identity = self._identity(path=cli, source="managed", commit=self.runtime_lock.commit)
            return PiCommand(argv=("node", str(cli)), identity=identity)
        explicit = self.environ.get(ENV_PI_COMMAND)
        if explicit:
            path = Path(explicit)
            identity = self._identity(path=path, source="explicit_override", commit=None)
            return PiCommand(argv=(str(path),), identity=identity)

        cli = self.source_dir / self.runtime_lock.executable
        if cli.is_file() and self._has_valid_active_marker():
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
        self._require_valid_active_marker()
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
            pi_ai_version=self.runtime_lock.pi_ai_version,
            patches_sha256=self.runtime_lock.patches_sha256,
        )

    def _has_valid_active_marker(self) -> bool:
        if not self.active_marker.exists():
            return False
        self._require_valid_active_marker()
        return True

    def _require_valid_active_marker(self) -> None:
        marker = self.active_marker
        if not marker.is_file():
            raise PiRuntimeLocatorError(f"Managed Pi active marker is missing or invalid: {marker}")

        try:
            lines = marker.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise PiRuntimeLocatorError(f"Managed Pi active marker cannot be read: {marker}") from exc

        if len(lines) != 4:
            raise PiRuntimeLocatorError(f"Managed Pi active marker is malformed: {marker}")
        marker_source = Path(lines[0])
        if not marker_source.is_absolute() or marker_source.resolve() != self.source_dir.resolve():
            raise PiRuntimeLocatorError("Managed Pi active marker source path does not match the managed source directory")

        values: dict[str, str] = {}
        for line in lines[1:]:
            key, separator, value = line.partition("=")
            if not separator or not key or key in values:
                raise PiRuntimeLocatorError(f"Managed Pi active marker is malformed: {marker}")
            values[key] = value

        expected = {
            "commit": self.runtime_lock.commit,
            "lock_sha256": self.runtime_lock.sha256,
            "patches_sha256": self.runtime_lock.patches_sha256,
        }
        if values != expected:
            raise PiRuntimeLocatorError("Managed Pi active marker identity does not match the runtime lock")

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        self.pi_runtime_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = self.runner(
                command,
                cwd=self.pi_runtime_dir,
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
