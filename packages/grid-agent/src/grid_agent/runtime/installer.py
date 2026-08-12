from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity, PiRuntimeLock


Runner = Callable[..., subprocess.CompletedProcess[str]]


class PiRuntimeInstallerError(RuntimeError):
    pass


class PiRuntimeInstaller:
    def __init__(
        self,
        runtime_lock: PiRuntimeLock,
        pi_runtime_dir: Path,
        *,
        runner: Runner | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.runtime_lock = runtime_lock
        self.pi_runtime_dir = Path(pi_runtime_dir)
        self.runner = runner or subprocess.run
        self.timeout_seconds = timeout_seconds

    @property
    def source_dir(self) -> Path:
        return self.pi_runtime_dir / "source"

    @property
    def active_marker(self) -> Path:
        return self.pi_runtime_dir / "active"

    def install(self) -> PiCommand:
        source = self.source_dir
        source.mkdir(parents=True, exist_ok=True)

        if not (source / ".git").exists():
            self._run(["git", "init"])
        self._run(["git", "remote", "remove", "origin"], check=False)
        self._run(["git", "remote", "add", "origin", self.runtime_lock.repository])
        self._run(["git", "fetch", "--depth", "1", "origin", self.runtime_lock.commit])
        self._run(["git", "checkout", "--detach", self.runtime_lock.commit])
        self._run(["npm", "ci"], timeout=max(self.timeout_seconds, 300))
        self._run(["npm", "run", "build"], timeout=max(self.timeout_seconds, 300))

        cli = source / self.runtime_lock.executable
        if not cli.is_file():
            raise PiRuntimeInstallerError(f"Pi build did not produce expected executable: {cli}")

        version = self._probe_version(cli)
        if version != self.runtime_lock.package_version:
            raise PiRuntimeInstallerError(
                f"Pi runtime version mismatch: expected {self.runtime_lock.package_version}, got {version}"
            )

        self.active_marker.parent.mkdir(parents=True, exist_ok=True)
        self.active_marker.write_text(
            f"{source}\ncommit={self.runtime_lock.commit}\nlock_sha256={self.runtime_lock.sha256}\n",
            encoding="utf-8",
        )
        identity = PiRuntimeIdentity(
            path=cli,
            source="managed",
            commit=self.runtime_lock.commit,
            package_version=self.runtime_lock.package_version,
            lock_sha256=self.runtime_lock.sha256,
            version=version,
        )
        return PiCommand(argv=("node", str(cli)), identity=identity)

    def _probe_version(self, cli: Path) -> str:
        result = self._run(["node", str(cli), "--version"], timeout=15)
        return _parse_version(result.stdout)

    def _run(
        self,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        try:
            result = self.runner(
                command,
                cwd=self.source_dir,
                timeout=timeout or self.timeout_seconds,
                shell=False,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PiRuntimeInstallerError(f"Pi runtime command failed to start: {command!r}: {exc}") from exc

        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            message = f"Pi runtime command failed ({' '.join(command)})"
            if detail:
                message = f"{message}: {detail}"
            raise PiRuntimeInstallerError(message)
        return result


def _parse_version(stdout: str) -> str:
    for line in stdout.splitlines():
        value = line.strip()
        if value:
            return value.removeprefix("v")
    raise PiRuntimeInstallerError("Pi runtime version probe returned no version")
