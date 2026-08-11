from pathlib import Path

import pytest

from grid_agent.config.catalog import ProviderCatalog
from grid_agent.config.models import CliLLMOptions
from grid_agent.config.resolver import ConfigurationError, resolve_llm


@pytest.fixture
def catalog() -> ProviderCatalog:
    return ProviderCatalog.load()


@pytest.fixture(autouse=True)
def isolate_default_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's repository .env must not affect resolver unit tests."""
    monkeypatch.chdir(tmp_path)


def test_cli_wins_over_process_and_dotenv(tmp_path: Path, catalog: ProviderCatalog) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GRID_AGENT_LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=dotenv-key\n", encoding="utf-8")

    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openai", model="gpt-5.5"),
        environ={"GRID_AGENT_LLM_PROVIDER": "openrouter", "OPENAI_API_KEY": "process-key"},
        env_file=env_file,
    )

    assert resolved.config.provider == "openai"
    assert resolved.config.field_sources["provider"] == "cli"
    assert resolved.secret.value == "process-key"


def test_codex_rejects_base_url_override(catalog: ProviderCatalog) -> None:
    with pytest.raises(ConfigurationError, match="base URL"):
        resolve_llm(
            catalog=catalog,
            cli=CliLLMOptions(provider="openai-codex", base_url="https://proxy.invalid"),
            environ={},
            oauth_configured=lambda _: True,
        )


def test_minimax_uses_own_key_and_transport(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="minimax"),
        environ={"MINIMAX_API_KEY": "secret"},
    )

    assert resolved.config.credential_reference == "MINIMAX_API_KEY"
    assert resolved.config.compatibility_profile == "anthropic-messages"


@pytest.mark.parametrize(
    ("provider", "key_name", "model", "base_url", "pi_provider", "compatibility_profile"),
    [
        ("openai", "OPENAI_API_KEY", "gpt-5.5", "https://api.openai.com/v1", "openai", "openai-responses"),
        (
            "openrouter",
            "OPENROUTER_API_KEY",
            "moonshotai/kimi-k2.6",
            "https://openrouter.ai/api/v1",
            "openrouter",
            "pi-built-in",
        ),
        ("deepseek", "DEEPSEEK_API_KEY", "deepseek-v4-pro", "https://api.deepseek.com", "deepseek", "pi-built-in"),
        (
            "minimax",
            "MINIMAX_API_KEY",
            "MiniMax-M2.7",
            "https://api.minimax.io/anthropic",
            "minimax",
            "anthropic-messages",
        ),
    ],
)
def test_api_key_provider_defaults_are_fieldwise(
    catalog: ProviderCatalog,
    provider: str,
    key_name: str,
    model: str,
    base_url: str,
    pi_provider: str,
    compatibility_profile: str,
) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider=provider),
        environ={key_name: "secret"},
    )

    assert resolved.config.provider == provider
    assert resolved.config.model == model
    assert resolved.config.base_url == base_url
    assert resolved.config.auth_kind == "api_key_env"
    assert resolved.config.credential_reference == key_name
    assert resolved.config.timeout_seconds == 180.0
    assert resolved.config.max_retries == 2
    assert resolved.config.pi_provider == pi_provider
    assert resolved.config.compatibility_profile == compatibility_profile
    assert resolved.config.supports_tools is True
    assert resolved.config.descriptor_version == "2026-08-10.pi-0.80.6"
    assert resolved.config.field_sources["model"] == "default"
    assert resolved.config.field_sources["credential_reference"] == "default"


def test_resolution_layers_are_applied_per_field(tmp_path: Path, catalog: ProviderCatalog) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "GRID_AGENT_LLM_PROVIDER=deepseek",
                "GRID_AGENT_LLM_MODEL=dotenv-model",
                "GRID_AGENT_LLM_BASE_URL=https://dotenv.example/v1",
                "GRID_AGENT_LLM_API_KEY_ENV=DOTENV_KEY",
                "GRID_AGENT_LLM_TIMEOUT_SECONDS=33",
                "GRID_AGENT_LLM_MAX_RETRIES=4",
                "DOTENV_KEY=dotenv-secret",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(model="cli-model", max_retries=7),
        environ={
            "GRID_AGENT_LLM_PROVIDER": "openrouter",
            "GRID_AGENT_LLM_BASE_URL": "https://process.example/v1",
            "GRID_AGENT_LLM_TIMEOUT_SECONDS": "44",
            "GRID_AGENT_LLM_API_KEY_ENV": "PROCESS_KEY",
            "PROCESS_KEY": "process-secret",
        },
        env_file=env_file,
    )

    assert resolved.config.provider == "openrouter"
    assert resolved.config.model == "cli-model"
    assert resolved.config.base_url == "https://process.example/v1"
    assert resolved.config.credential_reference == "PROCESS_KEY"
    assert resolved.config.timeout_seconds == 44.0
    assert resolved.config.max_retries == 7
    assert resolved.secret.value == "process-secret"
    assert resolved.config.field_sources == {
        "provider": "process",
        "model": "cli",
        "base_url": "process",
        "credential_reference": "process",
        "timeout_seconds": "process",
        "max_retries": "cli",
    }


def test_dotenv_values_can_be_supplied_without_mutating_process_environment(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(),
        environ={"OPENAI_API_KEY": "process-secret"},
        dotenv_values={
            "GRID_AGENT_LLM_PROVIDER": "deepseek",
            "GRID_AGENT_LLM_API_KEY_ENV": "DOTENV_KEY",
            "DOTENV_KEY": "dotenv-secret",
        },
    )

    assert resolved.config.provider == "deepseek"
    assert resolved.config.credential_reference == "DOTENV_KEY"
    assert resolved.secret.value == "dotenv-secret"
    assert resolved.config.field_sources["provider"] == "dotenv"


def test_default_dotenv_path_is_cwd_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, catalog: ProviderCatalog) -> None:
    (tmp_path / ".env").write_text(
        "GRID_AGENT_LLM_PROVIDER=minimax\nMINIMAX_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    resolved = resolve_llm(catalog=catalog, cli=CliLLMOptions(), environ={})

    assert resolved.config.provider == "minimax"
    assert resolved.secret.value == "dotenv-secret"
    assert resolved.config.field_sources["provider"] == "dotenv"


def test_empty_optional_values_are_unset(tmp_path: Path, catalog: ProviderCatalog) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GRID_AGENT_LLM_MODEL=\nGRID_AGENT_LLM_BASE_URL=\nGRID_AGENT_LLM_API_KEY_ENV=\nOPENAI_API_KEY=secret\n",
        encoding="utf-8",
    )

    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(model="", base_url="", api_key_env=""),
        environ={},
        env_file=env_file,
    )

    assert resolved.config.model == "gpt-5.5"
    assert resolved.config.base_url == "https://api.openai.com/v1"
    assert resolved.config.credential_reference == "OPENAI_API_KEY"


@pytest.mark.parametrize(
    ("cli", "environ", "message"),
    [
        (CliLLMOptions(provider="unknown"), {"OPENAI_API_KEY": "secret"}, "provider"),
        (CliLLMOptions(model=123), {"OPENAI_API_KEY": "secret"}, "model"),
        (CliLLMOptions(base_url="ftp://example.invalid"), {"OPENAI_API_KEY": "secret"}, "absolute URL"),
        (CliLLMOptions(base_url="http://example.invalid"), {"OPENAI_API_KEY": "secret"}, "HTTPS"),
        (CliLLMOptions(timeout_seconds=0), {"OPENAI_API_KEY": "secret"}, "timeout"),
        (CliLLMOptions(max_retries=-1), {"OPENAI_API_KEY": "secret"}, "retries"),
    ],
)
def test_invalid_cli_winner_fails_without_fallback(
    catalog: ProviderCatalog,
    cli: CliLLMOptions,
    environ: dict[str, str],
    message: str,
) -> None:
    environ = {"GRID_AGENT_LLM_PROVIDER": "openai", **environ}

    with pytest.raises(ConfigurationError, match=message):
        resolve_llm(catalog=catalog, cli=cli, environ=environ)


def test_invalid_process_winner_fails_without_dotenv_fallback(tmp_path: Path, catalog: ProviderCatalog) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GRID_AGENT_LLM_PROVIDER=openai\nOPENAI_API_KEY=dotenv-secret\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="provider"):
        resolve_llm(
            catalog=catalog,
            cli=CliLLMOptions(),
            environ={"GRID_AGENT_LLM_PROVIDER": "not-real"},
            env_file=env_file,
        )


def test_loopback_http_base_urls_are_allowed(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(base_url="http://127.0.0.1:8000/v1"),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert resolved.config.base_url == "http://127.0.0.1:8000/v1"


def test_provider_is_never_inferred_from_credentials(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(),
        environ={"DEEPSEEK_API_KEY": "deepseek-secret", "OPENAI_API_KEY": "openai-secret"},
    )

    assert resolved.config.provider == "openai"
    assert resolved.secret.value == "openai-secret"


def test_custom_api_key_env_names_are_supported(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openrouter", api_key_env="CUSTOM_ROUTER_KEY"),
        environ={"CUSTOM_ROUTER_KEY": "secret"},
    )

    assert resolved.config.credential_reference == "CUSTOM_ROUTER_KEY"
    assert resolved.config.field_sources["credential_reference"] == "cli"
    assert resolved.secret.value == "secret"


def test_missing_api_key_fails_with_reference_not_secret_value(catalog: ProviderCatalog) -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY") as exc_info:
        resolve_llm(catalog=catalog, cli=CliLLMOptions(provider="openai"), environ={})

    assert "secret" not in str(exc_info.value).lower()


def test_resolved_repr_redacts_api_secret(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="deepseek"),
        environ={"DEEPSEEK_API_KEY": "super-secret-value"},
    )

    assert "super-secret-value" not in repr(resolved)
    assert "super-secret-value" not in repr(resolved.secret)


def test_public_headers_are_provider_scoped(catalog: ProviderCatalog) -> None:
    openai = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openai"),
        environ={
            "OPENAI_API_KEY": "secret",
            "GRID_AGENT_OPENAI_ORGANIZATION": "org_123",
            "GRID_AGENT_OPENAI_PROJECT": "proj_123",
            "GRID_AGENT_OPENROUTER_HTTP_REFERER": "https://app.example",
            "GRID_AGENT_OPENROUTER_APP_NAME": "Grid Agent",
        },
    )
    openrouter = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openrouter"),
        environ={
            "OPENROUTER_API_KEY": "secret",
            "GRID_AGENT_OPENAI_ORGANIZATION": "org_123",
            "GRID_AGENT_OPENAI_PROJECT": "proj_123",
            "GRID_AGENT_OPENROUTER_HTTP_REFERER": "https://app.example",
            "GRID_AGENT_OPENROUTER_APP_NAME": "Grid Agent",
        },
    )

    assert openai.config.public_headers == {
        "OpenAI-Organization": "org_123",
        "OpenAI-Project": "proj_123",
    }
    assert openrouter.config.public_headers == {
        "HTTP-Referer": "https://app.example",
        "X-Title": "Grid Agent",
    }


def test_codex_uses_project_oauth_without_api_key_or_public_headers(catalog: ProviderCatalog) -> None:
    resolved = resolve_llm(
        catalog=catalog,
        cli=CliLLMOptions(provider="openai-codex"),
        environ={
            "OPENAI_API_KEY": "should-not-be-used",
            "GRID_AGENT_OPENAI_ORGANIZATION": "org_123",
            "GRID_AGENT_OPENAI_PROJECT": "proj_123",
        },
        oauth_configured=lambda profile: profile == "openai-codex",
    )

    assert resolved.config.auth_kind == "pi_oauth"
    assert resolved.config.credential_reference == "openai-codex"
    assert resolved.config.base_url == "https://chatgpt.com/backend-api"
    assert resolved.config.public_headers == {}
    assert resolved.secret is None


def test_codex_requires_oauth_status_callback(catalog: ProviderCatalog) -> None:
    with pytest.raises(ConfigurationError, match="OAuth"):
        resolve_llm(
            catalog=catalog,
            cli=CliLLMOptions(provider="openai-codex"),
            environ={},
            oauth_configured=lambda _: False,
        )
