from __future__ import annotations

import json
from dataclasses import replace
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
    legacy_query = "grid" + "_query"
    assert "domain-tools.mjs" in joined
    assert "hardened-bash.mjs" not in joined
    assert legacy_query not in joined
    assert "--no-builtin-tools" in launch.argv
    assert "--tools" not in launch.argv


def test_pi_launch_passes_domain_tool_paths_in_environment(tmp_path: Path) -> None:
    resolved = _resolved_openai()
    paths = _runtime_paths(tmp_path)

    launch = build_pi_launch(resolved, paths, base_environment={"PATH": "/bin", "HOME": "/tmp"})

    assert launch.environment["GRID_AGENT_TOOL_CATALOG"] == str(paths.tool_catalog_path)
    assert launch.environment["GRID_AGENT_GUIDE_INDEX"] == str(paths.guide_index_path)
    assert launch.environment["GRID_AGENT_WORKSPACE"] == str(paths.workspace)
    assert "GRID_AGENT_ANSWER_DRAFT" not in launch.environment
    assert launch.environment["OPENAI_API_KEY"] == "super-secret"


def test_pi_launch_exposes_analysis_paths_only_when_configured(tmp_path: Path) -> None:
    resolved = _resolved_openai()
    legacy_paths = _runtime_paths(tmp_path / "legacy")
    analysis_base_paths = _runtime_paths(tmp_path / "analysis")
    analysis_paths = replace(
        analysis_base_paths,
        active_turn_path=tmp_path / "analysis/run/active-turn.json",
        analysis_context_view_path=tmp_path / "analysis/run/context/analysis-context-view.json",
    )

    legacy_launch = build_pi_launch(resolved, legacy_paths, base_environment={"PATH": "/bin", "HOME": "/tmp"})
    analysis_launch = build_pi_launch(resolved, analysis_paths, base_environment={"PATH": "/bin", "HOME": "/tmp"})

    assert "GRID_AGENT_ACTIVE_TURN" not in legacy_launch.environment
    assert "GRID_AGENT_ANALYSIS_CONTEXT_VIEW" not in legacy_launch.environment
    assert analysis_launch.environment["GRID_AGENT_ACTIVE_TURN"] == str(analysis_paths.active_turn_path)
    assert analysis_launch.environment["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"] == str(
        analysis_paths.analysis_context_view_path
    )


def test_pi_launch_exposes_native_capture_paths_only_when_configured(
    tmp_path: Path,
) -> None:
    legacy = _runtime_paths(tmp_path / "legacy")
    native = replace(
        _runtime_paths(tmp_path / "native"),
        trajectory_requests_path=tmp_path / "native/run/requests",
        trajectory_capture_state_path=tmp_path
        / "native/run/context/trajectory-capture-state.json",
        trajectory_allowed_refs_path=tmp_path
        / "native/run/context/trajectory-allowed-refs.json",
        trajectory_acks_path=tmp_path
        / "native/.grid-agent/trajectory-acks/analysis-test",
    )

    legacy_launch = build_pi_launch(
        _resolved_openai(),
        legacy,
        base_environment={"PATH": "/bin", "HOME": "/tmp"},
    )
    native_launch = build_pi_launch(
        _resolved_openai(),
        native,
        base_environment={"PATH": "/bin", "HOME": "/tmp"},
    )

    for key in (
        "GRID_AGENT_TRAJECTORY_REQUESTS",
        "GRID_AGENT_TRAJECTORY_CAPTURE_STATE",
        "GRID_AGENT_TRAJECTORY_ALLOWED_REFS",
        "GRID_AGENT_TRAJECTORY_ACKS",
    ):
        assert key not in legacy_launch.environment
    assert "GRID_AGENT_PROVIDER_ID" not in native_launch.environment
    assert "GRID_AGENT_MODEL_ID" not in native_launch.environment
    assert native_launch.environment["GRID_AGENT_TRAJECTORY_REQUESTS"] == str(
        native.trajectory_requests_path
    )
    assert native_launch.environment["GRID_AGENT_TRAJECTORY_CAPTURE_STATE"] == str(
        native.trajectory_capture_state_path
    )
    assert native_launch.environment["GRID_AGENT_TRAJECTORY_ALLOWED_REFS"] == str(
        native.trajectory_allowed_refs_path
    )
    assert native_launch.environment["GRID_AGENT_TRAJECTORY_ACKS"] == str(
        native.trajectory_acks_path
    )
    trajectory_acks_path = native.trajectory_acks_path
    assert trajectory_acks_path is not None
    assert trajectory_acks_path.is_dir()
    assert trajectory_acks_path.parent.stat().st_mode & 0o777 == 0o700
    assert trajectory_acks_path.stat().st_mode & 0o777 == 0o700
    trajectory_environment = {
        key: value
        for key, value in native_launch.environment.items()
        if key.startswith("GRID_AGENT_TRAJECTORY")
    }
    assert "super-secret" not in json.dumps(trajectory_environment)


def test_pi_launch_exposes_verified_pi_runtime_identity(tmp_path: Path) -> None:
    paths = _runtime_paths(tmp_path)

    launch = build_pi_launch(
        _resolved_openai(),
        paths,
        base_environment={"PATH": "/bin", "HOME": "/tmp"},
    )

    assert launch.environment["GRID_AGENT_PI_CODING_AGENT_VERSION"] == "0.80.6"
    assert launch.environment["GRID_AGENT_PI_AI_VERSION"] == "0.80.6"
    assert (
        launch.environment["GRID_AGENT_PI_SOURCE_COMMIT"]
        == "2b3fda9921b5590f285165287bd442a25817f17b"
    )
    assert launch.environment["GRID_AGENT_PI_PATCH_SET_SHA256"] == "4" * 64


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
                pi_ai_version="0.80.6",
                patches_sha256="4" * 64,
                commit="2b3fda9921b5590f285165287bd442a25817f17b",
            ),
        ),
        project_pi_dir=project_paths.pi_agent_dir,
        session_dir=tmp_path / "run/pi",
        workspace=tmp_path / "run",
        gridctl_dir=tmp_path / "run/bin",
        extension_path=tmp_path / "packages/pi-grid-tools/src/domain-tools.mjs",
        tool_catalog_path=tmp_path / "run/tool-catalog.json",
        guide_index_path=tmp_path / "run/guide-index.json",
        system_policy_path=tmp_path / "configs/runtime/grid-agent-system-policy.md",
    )
