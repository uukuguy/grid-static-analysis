"""Loopback-only Uvicorn configuration for the trajectory API."""

from __future__ import annotations

from fastapi import FastAPI
from uvicorn import Config


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def build_server_config(app: FastAPI, *, host: str = "127.0.0.1", port: int = 8765) -> Config:
    """Return a Uvicorn configuration only for an explicit loopback host."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError("trajectory server host must be loopback")
    return Config(app, host=host, port=port, log_config=None, access_log=False)


__all__ = ["LOOPBACK_HOSTS", "build_server_config"]
