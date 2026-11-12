from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.core.app import create_core_app
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.singbox.config import (
    ClientConfigSpec,
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_client_config,
    build_server_config,
    config_digest,
)


def _engine(settings: Settings) -> Path:
    path = Path(settings.engine_path or settings.paths.engine_binary)
    assert path.is_file(), f"sing-box binary not found at {path}"
    return path


def _server_config() -> dict:
    return build_server_config(
        ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="vless",
                    enabled=True,
                    listen="127.0.0.1",
                    port=14443,
                    reality=RealitySpec(
                        private_key="IFxghqMsaCYgG6UXJM4998r_8OLm3U98Tt3SgzfB3Xk",
                        short_id="55e1651e1a99195b",
                    ),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password="c3M=",
                )
            ],
            clash_secret="test",
            enable_v2ray_api=False,
        )
    )


@pytest.mark.integration
def test_core_api_apply_and_stop(settings: Settings) -> None:
    _engine(settings)
    app = create_core_app(settings)
    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get("/v1/status").status_code == 401
        token = settings.paths.core_token_path.read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        status = client.get("/v1/status", headers=headers)
        assert status.status_code == 200

        config = _server_config()
        applied = client.post(
            "/v1/apply",
            json={"config": config, "sha256": config_digest(config), "role": "server"},
            headers=headers,
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["running"] is True
        assert settings.paths.last_good_path.is_file()

        logs = client.get("/v1/logs?tail=20", headers=headers)
        assert logs.status_code == 200

        stopped = client.post("/v1/stop", headers=headers)
        assert stopped.status_code == 200
        assert stopped.json()["running"] is False


@pytest.mark.integration
def test_core_rejects_digest_mismatch(settings: Settings) -> None:
    _engine(settings)
    app = create_core_app(settings)
    with TestClient(app) as client:
        token = settings.paths.core_token_path.read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/v1/apply",
            json={"config": _server_config(), "sha256": "0" * 64, "role": "server"},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "digest_mismatch"


@pytest.mark.integration
def test_core_rejects_wrong_role(settings: Settings) -> None:
    _engine(settings)
    app = create_core_app(settings)
    with TestClient(app) as client:
        token = settings.paths.core_token_path.read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        endpoint = Endpoint(
            tag="reality",
            protocol=Protocol.VLESS_REALITY,
            name="HK",
            server="127.0.0.1",
            port=443,
            uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
            tls=TLSConfig(reality_public_key="pub", reality_short_id="sid"),
        )
        config = build_client_config(
            ClientConfigSpec(endpoints=[endpoint], mode="tun", clash_secret="test")
        )
        response = client.post(
            "/v1/apply",
            json={"config": config, "sha256": config_digest(config), "role": "client"},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "role_mismatch"
