from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ostium.engine.singbox.clash_api import ClashApi


@pytest.mark.asyncio
async def test_clash_api_headers_without_secret(tmp_path: Path) -> None:
    api = ClashApi(tmp_path / "missing.secret")
    with respx.mock:
        route = respx.get("http://127.0.0.1:19090/version").mock(
            return_value=httpx.Response(200, json={"version": "1.14.4"})
        )
        assert await api.version() == {"version": "1.14.4"}
        assert "Authorization" not in route.calls[0].request.headers

    with respx.mock:
        respx.get("http://127.0.0.1:19090/version").mock(return_value=httpx.Response(500))
        assert await api.version() is None

    with respx.mock:
        respx.get("http://127.0.0.1:19090/proxies").mock(
            return_value=httpx.Response(200, json={"proxies": {"a": {}}})
        )
        assert await api.proxies() == {"proxies": {"a": {}}}
    with respx.mock:
        respx.get("http://127.0.0.1:19090/proxies").mock(side_effect=httpx.ConnectError("down"))
        assert await api.proxies() == {}


@pytest.mark.asyncio
async def test_clash_api_failures(tmp_path: Path) -> None:
    api = ClashApi(tmp_path / "secret")
    with respx.mock:
        respx.get("http://127.0.0.1:19090/connections").mock(side_effect=httpx.ConnectError("down"))
        data = await api.connections()
        assert data["unavailable"] is True
        assert data["connections"] == []

        respx.delete("http://127.0.0.1:19090/connections/abc").mock(
            return_value=httpx.Response(404)
        )
        assert await api.close_connection("abc") is False
        respx.delete("http://127.0.0.1:19090/connections/abc").mock(
            side_effect=httpx.ConnectError("down")
        )
        assert await api.close_connection("abc") is False

        respx.delete("http://127.0.0.1:19090/connections").mock(return_value=httpx.Response(500))
        assert await api.close_all() is False
        respx.delete("http://127.0.0.1:19090/connections").mock(
            side_effect=httpx.ConnectError("down")
        )
        assert await api.close_all() is False
