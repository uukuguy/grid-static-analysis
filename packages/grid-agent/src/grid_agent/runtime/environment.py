from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from grid_agent.config.models import ResolvedLLM
from grid_agent.runtime.lock import PiCommand


@dataclass(frozen=True)
class RuntimePaths:
    command: PiCommand
    project_pi_dir: Path
    session_dir: Path
    workspace: Path
    gridctl_dir: Path
    extension_path: Path
    tool_catalog_path: Path
    guide_index_path: Path
    answer_draft_path: Path
    system_policy_path: Path
    active_turn_path: Path | None = None
    analysis_context_view_path: Path | None = None
    trajectory_requests_path: Path | None = None
    trajectory_capture_state_path: Path | None = None
    trajectory_allowed_refs_path: Path | None = None
    provider_id: str | None = None
    model_id: str | None = None


@dataclass(frozen=True)
class PiLaunch:
    argv: tuple[str, ...]
    environment: dict[str, str]


def build_pi_launch(resolved: ResolvedLLM, paths: RuntimePaths, *, base_environment: dict[str, str] | None = None) -> PiLaunch:
    environment = build_pi_environment(resolved, paths, base_environment=base_environment)
    argv = (
        *paths.command.argv, "--mode", "rpc", "--provider", resolved.config.pi_provider, "--model", resolved.config.model,
        "--session-dir", str(paths.session_dir), "--system-prompt", str(paths.system_policy_path), "--no-extensions",
        "--no-skills", "--no-prompt-templates", "--no-context-files", "--extension", str(paths.extension_path),
        "--no-builtin-tools",
    )
    return PiLaunch(argv=argv, environment=environment)


def build_pi_environment(resolved: ResolvedLLM, paths: RuntimePaths, *, base_environment: dict[str, str] | None = None) -> dict[str, str]:
    source = base_environment or dict(os.environ)
    allowed = {key: value for key, value in source.items() if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"}}
    allowed["PATH"] = str(paths.gridctl_dir) + os.pathsep + allowed.get("PATH", "")
    allowed["PI_CODING_AGENT_DIR"] = str(paths.project_pi_dir)
    allowed["PI_CODING_AGENT_SESSION_DIR"] = str(paths.session_dir)
    # A live model run must be able to reach its provider.  Keep offline mode as
    # an explicit diagnostic override instead of silently disabling networking.
    if source.get("GRID_AGENT_PI_OFFLINE") == "1":
        allowed["PI_OFFLINE"] = "1"
    allowed["GRID_AGENT_WORKSPACE"] = str(paths.workspace)
    allowed["GRID_AGENT_TOOL_CATALOG"] = str(paths.tool_catalog_path)
    allowed["GRID_AGENT_GUIDE_INDEX"] = str(paths.guide_index_path)
    allowed["GRID_AGENT_ANSWER_DRAFT"] = str(paths.answer_draft_path)
    if paths.active_turn_path is not None:
        allowed["GRID_AGENT_ACTIVE_TURN"] = str(paths.active_turn_path)
    if paths.analysis_context_view_path is not None:
        allowed["GRID_AGENT_ANALYSIS_CONTEXT_VIEW"] = str(paths.analysis_context_view_path)
    native_capture = (
        paths.trajectory_requests_path,
        paths.trajectory_capture_state_path,
        paths.trajectory_allowed_refs_path,
        paths.provider_id,
        paths.model_id,
    )
    if all(value is not None for value in native_capture):
        allowed["GRID_AGENT_TRAJECTORY_REQUESTS"] = str(paths.trajectory_requests_path)
        allowed["GRID_AGENT_TRAJECTORY_CAPTURE_STATE"] = str(
            paths.trajectory_capture_state_path
        )
        allowed["GRID_AGENT_TRAJECTORY_ALLOWED_REFS"] = str(
            paths.trajectory_allowed_refs_path
        )
        allowed["GRID_AGENT_PROVIDER_ID"] = str(paths.provider_id)
        allowed["GRID_AGENT_MODEL_ID"] = str(paths.model_id)
    if resolved.secret is not None:
        allowed[resolved.config.credential_reference] = resolved.secret.value
        allowed["GRID_AGENT_SECRET_ENV_NAMES"] = resolved.config.credential_reference
    return allowed
