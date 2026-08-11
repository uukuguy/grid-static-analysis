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
    prompt_path: Path


@dataclass(frozen=True)
class PiLaunch:
    argv: tuple[str, ...]
    environment: dict[str, str]


def build_pi_launch(resolved: ResolvedLLM, paths: RuntimePaths, *, base_environment: dict[str, str] | None = None) -> PiLaunch:
    environment = build_pi_environment(resolved, paths, base_environment=base_environment)
    argv = (
        *paths.command.argv, "--mode", "rpc", "--provider", resolved.config.pi_provider, "--model", resolved.config.model,
        "--session-dir", str(paths.session_dir), "--system-prompt", str(paths.prompt_path), "--no-extensions", "--no-skills",
        "--no-prompt-templates", "--no-context-files", "--extension", str(paths.extension_path), "--tools", "read,bash,grid_query",
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
    if resolved.secret is not None:
        allowed[resolved.config.credential_reference] = resolved.secret.value
        allowed["GRID_AGENT_SECRET_ENV_NAMES"] = resolved.config.credential_reference
    return allowed
