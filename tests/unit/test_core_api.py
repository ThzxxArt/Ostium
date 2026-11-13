from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ostium.config import Role, Settings
from ostium.engine.core_api import CoreApiError, CoreClient


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        core_url="http://127.0.0.1:8788",
        dev=True,
    )
    value.paths.ensure()
    return value


@pytest.mark.asyncio
async def test_core_client_methods(tmp_path: Path) -> None:
    client = CoreClient(_settings(tmp_path), timeout=1)
    with respx.mock:
        status = respx.get("http://127.0.0.1:8788/v1/status").mock(
            return_value=httpx.Response(200, json={"running": True})
        )
        assert await client.status() == {"running": True}
        assert status.calls[0].request.headers["Authorization"].startswith("Bearer ")

        apply_route = respx.post("http://127.0.0.1:8788/v1/apply").mock(
            return_value=httpx.Response(200, json={"running": True})
        )
        assert await client.apply({"log": {}}, "0" * 64, "server") == {"running": True}
        assert b'"sha256"' in apply_route.calls[0].request.content
        assert b'"allow_lan":false' in apply_route.calls[0].request.content

        respx.post("http://127.0.0.1:8788/v1/reload").mock(
            return_value=httpx.Response(200, json={"running": True})
        )
        assert (await client.reload())["running"] is True
        respx.post("http://127.0.0.1:8788/v1/stop").mock(
            return_value=httpx.Response(200, json={"running": False})
        )
        assert (await client.stop())["running"] is False
        respx.get("http://127.0.0.1:8788/v1/logs").mock(
            return_value=httpx.Response(200, text="line")
        )
        assert await client.logs(10) == "line"
        respx.get("http://127.0.0.1:8788/v1/config").mock(
            return_value=httpx.Response(200, json={"log": {"level": "info"}})
        )
        assert await client.config() == {"log": {"level": "info"}}

        respx.get("http://127.0.0.1:8788/v1/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        assert await client.health() == {"status": "ok"}


@pytest.mark.asyncio
async def test_core_client_errors(tmp_path: Path) -> None:
    client = CoreClient(_settings(tmp_path), timeout=1)
    with respx.mock:
        respx.get("http://127.0.0.1:8788/v1/status").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(CoreApiError) as unreachable:
            await client.status()
        assert unreachable.value.code == "core_unreachable"
        assert unreachable.value.status_code == 503

        respx.get("http://127.0.0.1:8788/v1/status").mock(
            return_value=httpx.Response(422, json={"detail": "bad", "code": "engine_check_failed"})
        )
        with pytest.raises(CoreApiError) as json_error:
            await client.status()
        assert json_error.value.code == "engine_check_failed"
        assert json_error.value.detail == "bad"

        respx.get("http://127.0.0.1:8788/v1/status").mock(
            return_value=httpx.Response(500, text="plain error")
        )
        with pytest.raises(CoreApiError) as text_error:
            await client.status()
        assert text_error.value.detail == "plain error"
        assert text_error.value.code == "core_error"

        respx.get("http://127.0.0.1:8788/v1/health").mock(return_value=httpx.Response(503))
        with pytest.raises(CoreApiError):
            await client.health()
        respx.get("http://127.0.0.1:8788/v1/health").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(CoreApiError):
            await client.health()

        # A successful plain-text response without a JSON content type.
        respx.get("http://127.0.0.1:8788/v1/status").mock(
            return_value=httpx.Response(200, text="text")
        )
        with pytest.raises(ValueError):
            await client.status()
