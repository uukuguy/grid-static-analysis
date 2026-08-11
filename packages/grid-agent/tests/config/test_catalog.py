import json
from pathlib import Path

import pytest

from grid_agent.config.catalog import ConfigurationError, ProviderCatalog


APPROVED_PROVIDERS = {"openai", "openrouter", "deepseek", "openai-codex", "minimax"}


def test_provider_catalog_loads_exact_release_descriptor() -> None:
    catalog = ProviderCatalog.load()

    assert catalog.schema_version == 1
    assert catalog.descriptor_version == "2026-08-11.deepseek-v4-model-ids"
    assert catalog.default_provider == "openai"
    assert set(catalog.providers) == APPROVED_PROVIDERS
    assert catalog.provider("openai").default_model == "gpt-5.5"
    assert catalog.provider("openrouter").default_model == "moonshotai/kimi-k2.6"
    assert catalog.provider("deepseek").default_model == "deepseek-v4-pro"
    assert catalog.provider("deepseek").allowed_models == {"deepseek-v4-flash", "deepseek-v4-pro"}
    assert catalog.provider("openai-codex").base_url == "https://chatgpt.com/backend-api"
    assert catalog.provider("minimax").compatibility_profile == "anthropic-messages"


def test_catalog_rejects_unknown_or_missing_bound_provider(tmp_path: Path) -> None:
    catalog_path = tmp_path / "llm-providers.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "descriptor_version": "test",
                "default_provider": "openai",
                "providers": {
                    "openai": {
                        "default_model": "gpt-5.5",
                        "base_url": "https://api.openai.com/v1",
                        "base_url_policy": "override_allowed",
                        "auth": {"kind": "api_key_env", "default_env": "OPENAI_API_KEY"},
                        "pi_provider": "openai",
                        "compatibility_profile": "openai-responses",
                        "supports_tools": True,
                    },
                    "surprise": {
                        "default_model": "surprise",
                        "base_url": "https://example.invalid",
                        "base_url_policy": "override_allowed",
                        "auth": {"kind": "api_key_env", "default_env": "SURPRISE_API_KEY"},
                        "pi_provider": "surprise",
                        "compatibility_profile": "pi-built-in",
                        "supports_tools": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="exactly"):
        ProviderCatalog.load(catalog_path)
