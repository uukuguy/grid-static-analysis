from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from grid_agent.auth.store import AuthStatus, CODEX_PROVIDER, ProjectAuthStore
from grid_agent.runtime.lock import PiOAuthHelper


Runner = Callable[..., subprocess.CompletedProcess[str]]


class AuthServiceError(RuntimeError):
    pass


class AuthService:
    def __init__(self, store: ProjectAuthStore, helper: PiOAuthHelper, *, runner: Runner | None = None) -> None:
        self.store = store
        self.helper = helper
        self.runner = runner or subprocess.run

    def login(self, provider: str) -> AuthStatus:
        self._require_codex(provider)
        auth_directory = self.store.ensure_secure_directory()
        try:
            result = self.runner(
                [*self.helper.argv, "login", provider],
                cwd=auth_directory,
                shell=False,
                check=False,
            )
        except OSError as exc:
            raise AuthServiceError("Could not start the pinned Pi OAuth helper") from exc
        if result.returncode != 0:
            raise AuthServiceError("Pinned Pi OAuth login did not complete")
        status = self.store.status(provider)
        if not status.configured:
            raise AuthServiceError("Pinned Pi OAuth login did not create a project credential")
        self.store.path.chmod(0o600)
        return status

    def import_from_pi(self, source: Path | None = None) -> AuthStatus:
        return self.store.import_provider(source or Path.home() / ".pi/agent/auth.json", CODEX_PROVIDER)

    def status(self) -> AuthStatus:
        return self.store.status(CODEX_PROVIDER)

    def logout(self) -> AuthStatus:
        return self.store.logout(CODEX_PROVIDER)

    @staticmethod
    def _require_codex(provider: str) -> None:
        if provider != CODEX_PROVIDER:
            raise AuthServiceError("Only openai-codex OAuth is supported")
