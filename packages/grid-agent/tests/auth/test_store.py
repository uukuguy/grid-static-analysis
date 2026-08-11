from __future__ import annotations

import json
from pathlib import Path

from grid_agent.auth.store import ProjectAuthStore


def test_import_copies_only_codex_oauth_entry(tmp_path: Path) -> None:
    source = tmp_path / "global-auth.json"
    source.write_text(
        '{"openai-codex":{"type":"oauth","access":"secret"},"openai":{"type":"api_key","key":"forbidden"}}',
        encoding="utf-8",
    )
    store = ProjectAuthStore(tmp_path / "project" / "auth.json")

    status = store.import_provider(source, "openai-codex")

    assert status.configured is True
    assert store.read_redacted() == {"openai-codex": {"type": "oauth", "configured": True}}
    assert set(json.loads(store.path.read_text(encoding="utf-8"))) == {"openai-codex"}
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_logout_never_changes_source(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"openai-codex":{"type":"oauth","access":"secret"}}', encoding="utf-8")
    store = ProjectAuthStore(tmp_path / "project" / "auth.json")
    store.import_provider(source, "openai-codex")

    store.logout("openai-codex")

    assert "secret" in source.read_text(encoding="utf-8")
    assert store.status("openai-codex").configured is False
