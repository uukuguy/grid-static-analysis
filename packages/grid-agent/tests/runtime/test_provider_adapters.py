from __future__ import annotations

from pathlib import Path

from grid_agent.application.paths import ProjectPaths
from grid_agent.config.models import ResolvedLLM, ResolvedLLMConfig, SecretValue
from grid_agent.runtime.environment import RuntimePaths, build_pi_launch
from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity


def test_provider_launch_keeps_secret_out_of_argv(tmp_path: Path) -> None:
    resolved = ResolvedLLM(
        config=ResolvedLLMConfig(
            provider="openai", model="gpt-5.5", base_url="https://api.openai.com/v1", auth_kind="api_key_env",
            credential_reference="OPENAI_API_KEY", timeout_seconds=60, max_retries=0, pi_provider="openai",
            compatibility_profile="openai-responses", descriptor_version="test", public_headers={}, field_sources={}, supports_tools=True,
        ),
        secret=SecretValue("super-secret"),
    )
    project_paths = ProjectPaths.from_root(tmp_path)
    paths = RuntimePaths(
        command=PiCommand(argv=("pi",), identity=PiRuntimeIdentity(path=Path("pi"), source="explicit_override", package_version="0.80.6", lock_sha256="lock")),
        project_pi_dir=project_paths.pi_agent_dir, session_dir=tmp_path / "run/pi", workspace=tmp_path / "run", gridctl_dir=tmp_path / "run/bin", extension_path=tmp_path / "hardened-bash.mjs", prompt_path=tmp_path / "prompt.md",
    )

    launch = build_pi_launch(resolved, paths, base_environment={"PATH": "/bin", "HOME": "/tmp"})

    assert "super-secret" not in launch.argv
    assert launch.environment["OPENAI_API_KEY"] == "super-secret"
    assert launch.environment["GRID_AGENT_SECRET_ENV_NAMES"] == "OPENAI_API_KEY"
