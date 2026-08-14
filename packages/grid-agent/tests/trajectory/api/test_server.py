from __future__ import annotations

import pytest
from fastapi import FastAPI

from grid_agent.trajectory.api.server import LOOPBACK_HOSTS, build_server_config


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
