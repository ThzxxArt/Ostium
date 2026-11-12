"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ostium.api.app import build_app
from ostium.config import Role, Settings


def _engine_path() -> Path | None:
    candidates = [
        Path(os.environ.get("OSTIUM_TEST_ENGINE", "/tmp/opencode/sing-box")),
        Path("/usr/local/bin/sing-box"),
        Path("/usr/bin/sing-box"),
    ]
    return next((path for path in candidates if path.is_file()), None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    config = tmp_path / "config"
    state = tmp_path / "state"
    engine = _engine_path()
    value = Settings(
        role=Role.SERVER,
        host="127.0.0.1",
        port=18443,
        data_dir=data,
        config_dir=config,
        state_dir=state,
        core_token_file=data / "runtime" / "core.token",
        engine_path=str(engine) if engine else str(data / "core" / "sing-box"),
        proxy_ports=[443, 8388, 14443],
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    value.save()
    return value


@pytest.fixture
def api_client(settings: Settings) -> TestClient:
    app = build_app(settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "client-data"
    value = Settings(
        role=Role.CLIENT,
        host="127.0.0.1",
        port=18444,
        data_dir=data,
        config_dir=tmp_path / "client-config",
        state_dir=tmp_path / "client-state",
        core_token_file=data / "runtime" / "core.token",
        engine_path="/tmp/opencode/sing-box",
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    value.save()
    return value


@pytest.fixture
def client_api(client_settings: Settings) -> TestClient:
    app = build_app(client_settings)
    with TestClient(app) as client:
        yield client


def csrf(client: TestClient) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def setup_admin(
    client: TestClient,
    username: str = "admin",
    password: str = "verysecret123",
    domain: str = "example.com",
    role: str = "server",
) -> str:
    token = csrf(client)
    response = client.post(
        "/api/v1/setup",
        json={
            "role": role,
            "username": username,
            "password": password,
            "domain": domain,
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200, response.text
    return token


@pytest.fixture
def session_token(api_client: TestClient) -> str:
    return setup_admin(api_client)
