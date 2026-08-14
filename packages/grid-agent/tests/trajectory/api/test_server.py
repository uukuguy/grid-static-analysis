from __future__ import annotations

import pytest
from fastapi import FastAPI
from pathlib import Path

from grid_agent.application.paths import ProjectPaths
from grid_agent.trajectory.api.server import LOOPBACK_HOSTS, build_server_config, serve_trajectory


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_server_rejects_non_loopback_host(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_server_config(FastAPI(), host=host)


def test_server_defaults_to_ipv4_loopback_without_access_logging() -> None:
    config = build_server_config(FastAPI())

    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.access_log is False
    assert {"127.0.0.1", "::1", "localhost"} == LOOPBACK_HOSTS


def test_serve_trajectory_passes_loopback_config_to_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "grid_agent.trajectory.api.server.uvicorn.run",
        lambda app, **kwargs: observed.update(app=app, **kwargs),
    )

    serve_trajectory(
        project_paths=ProjectPaths.from_root(tmp_path),
        host="127.0.0.1",
        port=9000,
        runs_root=tmp_path / "runs",
    )

    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 9000
    assert observed["access_log"] is False
