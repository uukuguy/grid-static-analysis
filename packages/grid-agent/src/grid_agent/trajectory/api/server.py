"""Loopback-only Uvicorn configuration for the trajectory API."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from uvicorn import Config

from grid_agent.application.paths import ProjectPaths
from grid_agent.trajectory.api.app import create_trajectory_app
from grid_agent.trajectory.api.catalog import TrajectoryRunCatalog
from grid_agent.trajectory.api.cursor import CursorCodec
from grid_agent.trajectory.service import ProjectionService


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def build_server_config(app: FastAPI, *, host: str = "127.0.0.1", port: int = 8765) -> Config:
    """Return a Uvicorn configuration only for an explicit loopback host."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError("trajectory server host must be loopback")
    return Config(app, host=host, port=port, log_config=None, access_log=False)


def serve_trajectory(
    *, project_paths: ProjectPaths, host: str, port: int, runs_root: Path
) -> None:
    """Start the local read-only trajectory service without an answer envelope."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError("trajectory server host must be loopback")
    cache_root = project_paths.trajectory_cache_dir
    catalog = TrajectoryRunCatalog(
        runs_root=runs_root,
        cache_root=cache_root,
        projection_service=ProjectionService(cache_root),
    )
    codec = CursorCodec.load_or_create(cache_root / "cursor.key")
    uvicorn.run(
        create_trajectory_app(catalog, codec),
        host=host,
        port=port,
        log_config=None,
        access_log=False,
    )


__all__ = ["LOOPBACK_HOSTS", "build_server_config", "serve_trajectory"]
