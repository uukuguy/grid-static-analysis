from __future__ import annotations

import json
from pathlib import Path

from grid_agent.config.models import ResolvedLLM, ResolvedLLMConfig, SecretValue
from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.pi_config import PiConfigMaterializer


def test_materializer_writes_no_api_key(tmp_path: Path) -> None:
    resolved = ResolvedLLM(
        config=ResolvedLLMConfig(
            provider="openai", model="gpt-5.5", base_url="https://api.openai.com/v1", auth_kind="api_key_env",
            credential_reference="OPENAI_API_KEY", timeout_seconds=60, max_retries=0, pi_provider="openai",
            compatibility_profile="openai-responses", descriptor_version="test", public_headers={}, field_sources={}, supports_tools=True,
        ),
        secret=SecretValue("super-secret"),
    )

    paths = PiConfigMaterializer(ProjectPaths.from_root(tmp_path).pi_agent_dir).materialize(resolved)

    content = paths.settings_path.read_text() + paths.models_path.read_text()
    assert "super-secret" not in content
    assert "apiKey" not in content
    assert json.loads(paths.models_path.read_text()) == {}
    assert json.loads(paths.settings_path.read_text()) == {
        "httpIdleTimeoutMs": 60_000,
        "retry": {
            "enabled": False,
            "maxRetries": 0,
            "provider": {"maxRetries": 0, "timeoutMs": 60_000},
        },
    }


def test_materializer_passes_timeout_and_retry_budget_to_pi(tmp_path: Path) -> None:
    resolved = ResolvedLLM(
        config=ResolvedLLMConfig(
            provider="deepseek", model="deepseek-v4-flash-0731", base_url="https://api.deepseek.com/v1", auth_kind="api_key_env",
            credential_reference="DEEPSEEK_API_KEY", timeout_seconds=180, max_retries=2, pi_provider="deepseek",
            compatibility_profile="openai-completions", descriptor_version="test", public_headers={}, field_sources={}, supports_tools=True,
        ),
        secret=SecretValue("super-secret"),
    )

    paths = PiConfigMaterializer(ProjectPaths.from_root(tmp_path).pi_agent_dir).materialize(resolved)

    assert json.loads(paths.settings_path.read_text()) == {
        "httpIdleTimeoutMs": 180_000,
        "retry": {
            "enabled": True,
            "maxRetries": 2,
            "provider": {"maxRetries": 2, "timeoutMs": 180_000},
        },
    }
