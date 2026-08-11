from __future__ import annotations

import json
from pathlib import Path

from grid_agent.config.models import ResolvedLLM, ResolvedLLMConfig, SecretValue
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

    paths = PiConfigMaterializer(tmp_path / "var/pi/agent").materialize(resolved)

    content = paths.settings_path.read_text() + paths.models_path.read_text()
    assert "super-secret" not in content
    assert "apiKey" not in content
    assert json.loads(paths.models_path.read_text()) == {}
