from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from ostium.api import routes_events
from tests.conftest import setup_admin


def test_origin_matching_helpers() -> None:
    assert routes_events._origin_matches("https://example.com", "example.com") is True
    assert routes_events._origin_matches("https://evil.example", "example.com") is False
    assert routes_events._origin_matches("not a url", "example.com") is False
    assert routes_events._origin_matches("https://", "example.com") is False


def test_websocket_revalidates_and_closes_after_logout(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    monkeypatch.setattr(routes_events, "PING_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(routes_events, "AUTH_REVALIDATE_SECONDS", 0.0)
    with api_client.websocket_connect("/api/v1/events") as websocket:
        assert websocket.receive_json()["type"] == "hello"
        api_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": session_token})
        with pytest.raises(WebSocketDisconnect) as excinfo:
            for _ in range(20):
                websocket.receive_json()
        assert excinfo.value.code == 4401


def test_websocket_rejects_invalid_session(api_client: TestClient) -> None:
    api_client.cookies.set("ostium_session", "not-a-session")
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: SIM117
        with api_client.websocket_connect("/api/v1/events"):
            pass
    assert excinfo.value.code == 4401
    assert "expired" in excinfo.value.reason


def test_websocket_rejects_cross_origin(api_client: TestClient) -> None:
    setup_admin(api_client)
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        api_client.websocket_connect("/api/v1/events", headers={"origin": "https://evil.example"}),
    ):
        pass
    assert excinfo.value.code == 4403


def test_websocket_delivers_events(api_client: TestClient) -> None:
    setup_admin(api_client)
    with api_client.websocket_connect("/api/v1/events") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        api_client.portal.call(
            api_client.app.state.services.bus.publish, "test.event", {"value": 1}
        )
        event = websocket.receive_json()
        assert event["type"] == "test.event"
        assert event["data"] == {"value": 1}


def test_websocket_disconnect_is_clean(api_client: TestClient, monkeypatch) -> None:
    setup_admin(api_client)

    class DisconnectingQueue:
        async def get(self):  # type: ignore[no-untyped-def]
            raise WebSocketDisconnect()

    async def subscribe():
        return DisconnectingQueue()

    monkeypatch.setattr(api_client.app.state.services.bus, "subscribe", subscribe)
    with api_client.websocket_connect("/api/v1/events") as websocket:
        assert websocket.receive_json()["type"] == "hello"


def test_websocket_unexpected_error_closes(api_client: TestClient, monkeypatch) -> None:
    setup_admin(api_client)

    async def broken_wait(awaitable, timeout=None):  # type: ignore[no-untyped-def]
        awaitable.close()
        raise RuntimeError("stream broke")

    monkeypatch.setattr(routes_events.asyncio, "wait_for", broken_wait)
    with api_client.websocket_connect("/api/v1/events") as websocket:
        assert websocket.receive_json()["type"] == "hello"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()
