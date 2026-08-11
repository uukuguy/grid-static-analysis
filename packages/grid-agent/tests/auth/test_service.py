from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from grid_agent.auth.service import AuthService
from grid_agent.auth.store import ProjectAuthStore
from grid_agent.runtime.lock import PiOAuthHelper, PiRuntimeIdentity


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        cwd = Path(kwargs["cwd"])
        (cwd / "auth.json").write_text('{"openai-codex":{"type":"oauth","access":"secret"}}', encoding="utf-8")
        return subprocess.CompletedProcess(list(argv), 0, "", "")


def test_login_uses_project_owned_auth_path_and_redacts_status(tmp_path: Path) -> None:
    runner = FakeRunner()
    helper = PiOAuthHelper(
        argv=("node", "/pinned/pi-ai.js"),
        identity=PiRuntimeIdentity(
            path=Path("/pinned/pi-ai.js"),
            source="managed",
            package_version="0.80.6",
            lock_sha256="lock",
        ),
    )
    store = ProjectAuthStore(tmp_path / "var/pi/agent/auth.json")
    service = AuthService(store, helper, runner=runner)

    status = service.login("openai-codex")

    assert status.configured is True
    assert runner.calls[0][0] == ["node", "/pinned/pi-ai.js", "login", "openai-codex"]
    assert runner.calls[0][1]["cwd"] == tmp_path / "var/pi/agent"
    assert "secret" not in repr(status)
    assert json.loads(store.path.read_text(encoding="utf-8"))["openai-codex"]["access"] == "secret"
