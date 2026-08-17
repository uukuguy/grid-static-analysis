from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity, PiRuntimeLock, PiRuntimePatch


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
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.runtime_lock = runtime_lock
        self.pi_runtime_dir = Path(pi_runtime_dir)
        self.runner = runner or subprocess.run
        self.timeout_seconds = timeout_seconds
        self.environ = dict(os.environ if environ is None else environ)

    @property
    def source_dir(self) -> Path:
        return self.pi_runtime_dir / "source"

    @property
    def active_marker(self) -> Path:
        return self.pi_runtime_dir / "active"

    def install(self) -> PiCommand:
        source = self._prepare_source_dir()
        self._clear_active_marker()
        self._verify_patch_bytes()

        if not (source / ".git").exists():
            self._run(["git", "init"])
        self._run(["git", "remote", "remove", "origin"], check=False)
        self._run(["git", "remote", "add", "origin", self.runtime_lock.repository])
        self._run(["git", "fetch", "--depth", "1", "origin", self.runtime_lock.commit])
        self._run(["git", "checkout", "--detach", self.runtime_lock.commit])
        self._run(["git", "reset", "--hard", self.runtime_lock.commit])
        self._run(["git", "clean", "-fdx"])
        for patch in self.runtime_lock.patches:
            self._apply_patch(patch)
        self._run(["npm", "ci"], timeout=max(self.timeout_seconds, 300))
        self._hydrate_pinned_pi_ai()
        self._run_pi_build()

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
            f"{source}\n"
            f"commit={self.runtime_lock.commit}\n"
            f"lock_sha256={self.runtime_lock.sha256}\n"
            f"patches_sha256={self.runtime_lock.patches_sha256}\n",
            encoding="utf-8",
        )
        identity = PiRuntimeIdentity(
            path=cli,
            source="managed",
            commit=self.runtime_lock.commit,
            package_version=self.runtime_lock.package_version,
            lock_sha256=self.runtime_lock.sha256,
            pi_ai_version=self.runtime_lock.pi_ai_version,
            patches_sha256=self.runtime_lock.patches_sha256,
            version=version,
        )
        return PiCommand(argv=("node", str(cli)), identity=identity)

    def _prepare_source_dir(self) -> Path:
        runtime_root = self._prepare_runtime_root()
        source = self.source_dir
        if source.is_symlink():
            raise PiRuntimeInstallerError(f"Pi runtime source directory must not be a symlink: {source}")

        try:
            source.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PiRuntimeInstallerError(f"Pi runtime source directory could not be created: {source}") from exc
        if source.is_symlink() or not source.is_dir():
            raise PiRuntimeInstallerError(f"Pi runtime source path is not a safe directory: {source}")

        resolved_source = source.resolve()
        try:
            resolved_source.relative_to(runtime_root)
        except ValueError as exc:
            raise PiRuntimeInstallerError(
                f"Pi runtime source directory must stay inside the managed runtime root: {source}"
            ) from exc
        return source

    def _prepare_runtime_root(self) -> Path:
        runtime_root = self.pi_runtime_dir
        if runtime_root.is_symlink():
            raise PiRuntimeInstallerError(f"Pi runtime root must not be a symlink: {runtime_root}")

        try:
            runtime_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PiRuntimeInstallerError(f"Pi runtime root could not be created: {runtime_root}") from exc
        if runtime_root.is_symlink() or not runtime_root.is_dir():
            raise PiRuntimeInstallerError(f"Pi runtime root is not a safe directory: {runtime_root}")
        return runtime_root.resolve()

    def _clear_active_marker(self) -> None:
        try:
            self.active_marker.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise PiRuntimeInstallerError(f"Pi runtime active marker could not be removed: {self.active_marker}") from exc

    def _apply_patch(self, patch: PiRuntimePatch) -> None:
        self._verify_patch_bytes(patch)
        patch_path = str(patch.path)
        self._run(["git", "apply", "--check", patch_path])
        self._run(["git", "apply", patch_path])

    def _verify_patch_bytes(self, patch: PiRuntimePatch | None = None) -> None:
        patches = (patch,) if patch is not None else self.runtime_lock.patches
        for item in patches:
            try:
                actual = hashlib.sha256(item.path.read_bytes()).hexdigest()
            except OSError as exc:
                raise PiRuntimeInstallerError(f"Pi runtime patch cannot be read: {item.path}") from exc
            if actual != item.sha256:
                raise PiRuntimeInstallerError(
                    f"Pi runtime patch digest mismatch for {item.path}: expected {item.sha256}, got {actual}"
                )

    def _probe_version(self, cli: Path) -> str:
        result = self._run(["node", str(cli), "--version"], timeout=15)
        return _parse_version(result.stdout)

    def _run_pi_build(self) -> None:
        for workspace in (
            "@earendil-works/pi-tui",
            "@earendil-works/pi-agent-core",
            "@earendil-works/pi-coding-agent",
        ):
            self._run(["npm", "run", "build", "--workspace", workspace], timeout=max(self.timeout_seconds, 300))

    def _hydrate_pinned_pi_ai(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grid-agent-pi-ai-") as temporary:
            result = self._run(
                ["npm", "pack", "--json", "--pack-destination", temporary, f"@earendil-works/pi-ai@{self.runtime_lock.pi_ai_version}"],
                timeout=max(self.timeout_seconds, 300),
            )
            try:
                packages = json.loads(result.stdout)
                package = packages[0]
                filename = package["filename"]
                integrity = package["integrity"]
            except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise PiRuntimeInstallerError("npm pack did not return pinned pi-ai package metadata") from exc
            if integrity != self.runtime_lock.pi_ai_npm_integrity:
                raise PiRuntimeInstallerError("Pinned pi-ai package integrity mismatch")
            archive = Path(temporary, filename)
            if archive.parent != Path(temporary) or not archive.is_file():
                raise PiRuntimeInstallerError("npm pack did not produce the pinned pi-ai archive")
            self._run(["tar", "-xzf", str(archive), "-C", temporary])
            source_dist = Path(temporary, "package", "dist")
            target_dist = self.source_dir / "packages" / "ai" / "dist"
            if not source_dist.is_dir() or target_dist.is_symlink():
                raise PiRuntimeInstallerError("Pinned pi-ai archive does not contain a safe dist directory")
            shutil.rmtree(target_dist, ignore_errors=True)
            shutil.copytree(source_dist, target_dist)

    def _run(
        self,
        argv: Sequence[str],
        *,
        timeout: int | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
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
                env=dict(env) if env is not None else None,
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
