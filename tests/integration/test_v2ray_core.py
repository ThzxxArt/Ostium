from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.core.app import create_core_app
from ostium.engine.singbox.config import (
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_server_config,
    config_digest,
)
from ostium.engine.singbox.v2ray_stats import V2RayStatsClient

CUSTOM_CORE = Path("/tmp/opencode/sing-box-v2ray")


def test_custom_core_exposes_v2ray_stats(settings: Settings) -> None:
    if not CUSTOM_CORE.is_file():
        pytest.skip("custom with_v2ray_api core is not available")
    settings.engine_path = str(CUSTOM_CORE)
    config = build_server_config(
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
            enable_v2ray_api=True,
        )
    )
    app = create_core_app(settings)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {settings.paths.core_token_path.read_text().strip()}"}
        response = client.post(
            "/v1/apply",
            json={"config": config, "sha256": config_digest(config), "role": "server"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["running"] is True

        async def _query() -> dict[str, tuple[int, int]]:
            stats = V2RayStatsClient("127.0.0.1:19091")
            try:
                return await stats.query_users()
            finally:
                await stats.close()

        import asyncio

        result = asyncio.run(_query())
        assert isinstance(result, dict)
        client.post("/v1/stop", headers=headers)
