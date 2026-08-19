from __future__ import annotations

from pathlib import Path

import pytest

from grid_agent.application.paths import ProjectPaths
from grid_agent.config.models import ResolvedLLM, ResolvedLLMConfig, SecretValue
from grid_agent.runtime.environment import RuntimePaths, build_pi_launch
from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity


def _resolved(base_url: str = "https://api.openai.com/v1") -> ResolvedLLM:
    return ResolvedLLM(
        config=ResolvedLLMConfig(
            provider="openai", model="gpt-5.5", base_url=base_url, auth_kind="api_key_env",
            credential_reference="OPENAI_API_KEY", timeout_seconds=60, max_retries=0, pi_provider="openai",
            compatibility_profile="openai-responses", descriptor_version="test", public_headers={}, field_sources={}, supports_tools=True,
        ),
        secret=SecretValue("super-secret"),
    )


def _runtime_paths(tmp_path: Path) -> RuntimePaths:
    project_paths = ProjectPaths.from_root(tmp_path)
    return RuntimePaths(
        command=PiCommand(argv=("pi",), identity=PiRuntimeIdentity(path=Path("pi"), source="explicit_override", package_version="0.80.6", lock_sha256="lock")),
        project_pi_dir=project_paths.pi_agent_dir,
        session_dir=tmp_path / "run/pi",
        workspace=tmp_path / "run",
        gridctl_dir=tmp_path / "run/bin",
        extension_path=tmp_path / "domain-tools.mjs",
        tool_catalog_path=tmp_path / "run/tool-catalog.json",
        guide_index_path=tmp_path / "run/guide-index.json",
        system_policy_path=tmp_path / "system-policy.md",
    )


def test_provider_launch_keeps_secret_out_of_argv(tmp_path: Path) -> None:
    launch = build_pi_launch(
        _resolved(),
        _runtime_paths(tmp_path),
        base_environment={"PATH": "/bin", "HOME": "/tmp"},
    )

    assert "super-secret" not in launch.argv
    assert launch.environment["OPENAI_API_KEY"] == "super-secret"
    assert launch.environment["GRID_AGENT_SECRET_ENV_NAMES"] == "OPENAI_API_KEY"


@pytest.mark.parametrize(
    ("base_url", "existing", "expected"),
    [
        ("http://localhost:11234/v1", None, "localhost"),
        ("http://127.0.0.2:11234/v1", "internal.example", "internal.example,127.0.0.2"),
        ("http://[::1]:11234/v1", "localhost", "localhost,::1"),
        ("http://localhost:11234/v1", "internal.example,LOCALHOST", "internal.example,LOCALHOST"),
    ],
)
def test_provider_launch_bypasses_proxy_for_loopback_base_url(
    tmp_path: Path,
    base_url: str,
    existing: str | None,
    expected: str,
) -> None:
    parent_environment = {
        "PATH": "/bin",
        "HOME": "/tmp",
        "HTTP_PROXY": "http://proxy.example:8080",
        "HTTPS_PROXY": "http://proxy.example:8080",
    }
    if existing is not None:
        parent_environment["NO_PROXY"] = existing

    launch = build_pi_launch(
        _resolved(base_url),
        _runtime_paths(tmp_path),
        base_environment=parent_environment,
    )

    assert launch.environment["NO_PROXY"] == expected
    assert launch.environment["HTTP_PROXY"] == "http://proxy.example:8080"
    assert launch.environment["HTTPS_PROXY"] == "http://proxy.example:8080"


def test_provider_launch_keeps_external_provider_proxy_routing(tmp_path: Path) -> None:
    launch = build_pi_launch(
        _resolved("https://openrouter.ai/api/v1"),
        _runtime_paths(tmp_path),
        base_environment={
            "PATH": "/bin",
            "HOME": "/tmp",
            "HTTP_PROXY": "http://proxy.example:8080",
            "HTTPS_PROXY": "http://proxy.example:8080",
            "NO_PROXY": "internal.example",
        },
    )

    assert launch.environment["NO_PROXY"] == "internal.example"
