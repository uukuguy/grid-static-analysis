from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when LLM configuration cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class CliLLMOptions:
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float | int | str | None = None
    max_retries: int | str | None = None


@dataclass(frozen=True, slots=True)
class SecretValue:
    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedLLMConfig:
    provider: str
    model: str
    base_url: str
    auth_kind: str
    credential_reference: str
    timeout_seconds: float
    max_retries: int
    pi_provider: str
    compatibility_profile: str
    descriptor_version: str
    public_headers: Mapping[str, str]
    field_sources: Mapping[str, str]
    supports_tools: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_headers", MappingProxyType(dict(self.public_headers)))
        object.__setattr__(self, "field_sources", MappingProxyType(dict(self.field_sources)))


@dataclass(frozen=True, slots=True)
class ResolvedLLM:
    config: ResolvedLLMConfig
    secret: SecretValue | None = field(default=None, repr=False)
