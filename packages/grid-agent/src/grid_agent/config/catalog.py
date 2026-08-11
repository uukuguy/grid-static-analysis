from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from grid_agent.config.models import ConfigurationError


APPROVED_PROVIDERS = frozenset({"openai", "openrouter", "deepseek", "openai-codex", "minimax"})


@dataclass(frozen=True, slots=True)
class ProviderAuth:
    kind: Literal["api_key_env", "pi_oauth"]
    default_env: str | None = None
    profile: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    name: str
    default_model: str
    base_url: str
    base_url_policy: Literal["override_allowed", "fixed"]
    auth: ProviderAuth
    pi_provider: str
    compatibility_profile: str
    supports_tools: bool
    allowed_models: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class ProviderCatalog:
    schema_version: int
    descriptor_version: str
    default_provider: str
    providers: Mapping[str, ProviderDescriptor]

    @classmethod
    def load(cls, path: Path | None = None) -> "ProviderCatalog":
        catalog_path = path or _default_catalog_path()
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ProviderCatalog":
        providers_raw = raw.get("providers")
        if not isinstance(providers_raw, Mapping):
            raise ConfigurationError("Provider catalog must contain providers")

        provider_names = set(providers_raw)
        if provider_names != APPROVED_PROVIDERS:
            raise ConfigurationError(
                f"Provider catalog must bind exactly {sorted(APPROVED_PROVIDERS)}; got {sorted(provider_names)}"
            )

        providers = {
            name: _parse_provider(name, value)
            for name, value in providers_raw.items()
        }

        schema_version = raw.get("schema_version")
        if schema_version != 1:
            raise ConfigurationError("Provider catalog schema_version must be 1")

        descriptor_version = _required_string(raw, "descriptor_version")
        default_provider = _required_string(raw, "default_provider")
        if default_provider not in providers:
            raise ConfigurationError(f"Default provider {default_provider!r} is not in the provider catalog")

        return cls(
            schema_version=schema_version,
            descriptor_version=descriptor_version,
            default_provider=default_provider,
            providers=providers,
        )

    def provider(self, name: str) -> ProviderDescriptor:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown provider {name!r}") from exc


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[5] / "configs" / "llm-providers.json"


def _parse_provider(name: str, raw: Any) -> ProviderDescriptor:
    if not isinstance(raw, Mapping):
        raise ConfigurationError(f"Provider {name!r} must be an object")

    auth_raw = raw.get("auth")
    if not isinstance(auth_raw, Mapping):
        raise ConfigurationError(f"Provider {name!r} must include auth")

    auth_kind = _required_string(auth_raw, "kind")
    if auth_kind == "api_key_env":
        auth = ProviderAuth(kind="api_key_env", default_env=_required_string(auth_raw, "default_env"))
    elif auth_kind == "pi_oauth":
        auth = ProviderAuth(kind="pi_oauth", profile=_required_string(auth_raw, "profile"))
    else:
        raise ConfigurationError(f"Provider {name!r} has unsupported auth kind {auth_kind!r}")

    base_url_policy = _required_string(raw, "base_url_policy")
    if base_url_policy not in {"override_allowed", "fixed"}:
        raise ConfigurationError(f"Provider {name!r} has unsupported base URL policy {base_url_policy!r}")

    supports_tools = raw.get("supports_tools")
    if not isinstance(supports_tools, bool):
        raise ConfigurationError(f"Provider {name!r} must declare boolean supports_tools")

    return ProviderDescriptor(
        name=name,
        default_model=_required_string(raw, "default_model"),
        base_url=_required_string(raw, "base_url"),
        base_url_policy=base_url_policy,
        auth=auth,
        pi_provider=_required_string(raw, "pi_provider"),
        compatibility_profile=_required_string(raw, "compatibility_profile"),
        supports_tools=supports_tools,
        allowed_models=_optional_string_set(raw, "allowed_models"),
    )


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"Provider catalog field {key!r} must be a non-empty string")
    return value


def _optional_string_set(raw: Mapping[str, Any], key: str) -> frozenset[str] | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigurationError(f"Provider catalog field {key!r} must be a non-empty string list")
    return frozenset(value)
