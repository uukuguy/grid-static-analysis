from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from grid_agent.config.models import ResolvedLLM


@dataclass(frozen=True)
class PiConfigPaths:
    settings_path: Path
    models_path: Path


class PiConfigMaterializer:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def materialize(self, resolved: ResolvedLLM) -> PiConfigPaths:
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        settings_path = self.directory / "settings.json"
        models_path = self.directory / "models.json"
        timeout_ms = round(resolved.config.timeout_seconds * 1_000)
        retries = resolved.config.max_retries
        settings = {
            "httpIdleTimeoutMs": timeout_ms,
            "retry": {
                "enabled": retries > 0,
                "maxRetries": retries,
                "provider": {"timeoutMs": timeout_ms, "maxRetries": retries},
            },
        }
        settings_path.write_text(json.dumps(settings, separators=(",", ":")) + "\n", encoding="utf-8")
        is_official = resolved.config.base_url == "https://api.openai.com/v1" and not resolved.config.public_headers
        models = {} if is_official else {"providers": {resolved.config.pi_provider: {"baseUrl": resolved.config.base_url, "headers": dict(resolved.config.public_headers)}}}
        models_path.write_text(json.dumps(models, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(settings_path, 0o600)
        os.chmod(models_path, 0o600)
        return PiConfigPaths(settings_path=settings_path, models_path=models_path)
