from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from ostium.engine.singbox.clash_api import ClashApi


@pytest.mark.asyncio
async def test_clash_api_connections_and_close(tmp_path: Path) -> None:
    secret = tmp_path / "clash.secret"
    secret.write_text("test-secret")
    api = ClashApi(secret)
    with respx.mock:
        route = respx.get("http://127.0.0.1:19090/connections").mock(
            return_value=httpx.Response(
                200,
                json={"uploadTotal": 10, "downloadTotal": 20, "connections": []},
            )
        )
        data = await api.connections()
        assert data["uploadTotal"] == 10
        assert route.called
        assert route.calls[0].request.headers["Authorization"] == "Bearer test-secret"

        close = respx.delete("http://127.0.0.1:19090/connections/abc").mock(
            return_value=httpx.Response(204)
        )
        assert await api.close_connection("abc")
        assert close.called
        close_all = respx.delete("http://127.0.0.1:19090/connections").mock(
            return_value=httpx.Response(204)
        )
        assert await api.close_all()
        assert close_all.called
