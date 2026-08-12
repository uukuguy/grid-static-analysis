from __future__ import annotations

import json
from pathlib import Path

from grid_agent.config.models import ResolvedLLM, ResolvedLLMConfig, SecretValue
from grid_agent.application.paths import ProjectPaths
from grid_agent.runtime.environment import RuntimePaths, build_pi_launch
from grid_agent.runtime.lock import PiCommand, PiRuntimeIdentity
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


def test_pi_launch_exposes_only_project_tools(tmp_path: Path) -> None:
    resolved = _resolved_openai()
    launch = build_pi_launch(resolved, _runtime_paths(tmp_path))

    joined = " ".join(launch.argv)
    assert "domain-tools.mjs" in joined
    assert "hardened-bash.mjs" not in joined
    assert "grid_query" not in joined
    assert "--no-builtin-tools" in launch.argv
    assert "--tools" not in launch.argv


def test_pi_launch_passes_domain_tool_paths_in_environment(tmp_path: Path) -> None:
    resolved = _resolved_openai()
    paths = _runtime_paths(tmp_path)

    launch = build_pi_launch(resolved, paths, base_environment={"PATH": "/bin", "HOME": "/tmp"})

    assert launch.environment["GRID_AGENT_TOOL_CATALOG"] == str(paths.tool_catalog_path)
    assert launch.environment["GRID_AGENT_GUIDE_INDEX"] == str(paths.guide_index_path)
    assert launch.environment["GRID_AGENT_WORKSPACE"] == str(paths.workspace)
    assert launch.environment["GRID_AGENT_ANSWER_DRAFT"] == str(paths.answer_draft_path)
    assert launch.environment["OPENAI_API_KEY"] == "super-secret"


def _resolved_openai() -> ResolvedLLM:
    return ResolvedLLM(
        config=ResolvedLLMConfig(
            provider="openai",
            model="gpt-5.5",
            base_url="https://api.openai.com/v1",
            auth_kind="api_key_env",
            credential_reference="OPENAI_API_KEY",
            timeout_seconds=60,
            max_retries=0,
            pi_provider="openai",
            compatibility_profile="openai-responses",
            descriptor_version="test",
            public_headers={},
            field_sources={},
            supports_tools=True,
        ),
        secret=SecretValue("super-secret"),
    )


def _runtime_paths(tmp_path: Path) -> RuntimePaths:
    project_paths = ProjectPaths.from_root(tmp_path)
    return RuntimePaths(
        command=PiCommand(
            argv=("pi",),
            identity=PiRuntimeIdentity(
                path=Path("pi"),
                source="explicit_override",
                package_version="0.80.6",
                lock_sha256="lock",
            ),
        ),
        project_pi_dir=project_paths.pi_agent_dir,
        session_dir=tmp_path / "run/pi",
        workspace=tmp_path / "run",
        gridctl_dir=tmp_path / "run/bin",
        extension_path=tmp_path / "packages/pi-grid-tools/src/domain-tools.mjs",
        tool_catalog_path=tmp_path / "run/tool-catalog.json",
        guide_index_path=tmp_path / "run/guide-index.json",
        answer_draft_path=tmp_path / "run/answer-draft.json",
        system_policy_path=tmp_path / "configs/runtime/grid-agent-system-policy.md",
    )
