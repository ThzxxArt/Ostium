from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.engine.manager import EngineError
from ostium.services.stats import UserUsage
from ostium.util.time import utcnow
from tests.conftest import setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


class FakeStats:
    def __init__(self, user_id: str, name: str) -> None:
        self.usage = {user_id: UserUsage(user_id=user_id, name=name, up=10, down=20, online=True)}

    def snapshot(self) -> dict:
        return {
            "users": [
                {"id": key, "name": item.name, "online": True} for key, item in self.usage.items()
            ],
            "online": 1,
            "rate_up": 1.0,
            "rate_down": 2.0,
            "last_error": None,
        }


def test_user_lifecycle_and_subscriptions(api_client: TestClient, settings: Settings) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)

    async def applied(session: object) -> dict:
        return {"status": {"revision": "revision-1"}}

    api_client.app.state.services.engine.apply_server = applied  # type: ignore[method-assign]

    api_client.app.state.services.stats = None
    assert api_client.get("/api/v1/users").json() == {"users": [], "total": 0}

    invalid = api_client.post("/api/v1/users", json={"name": "bad<name"}, headers=headers)
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "user_error"

    bad_cycle = api_client.post(
        "/api/v1/users", json={"name": "alice", "quota_cycle": "weekly"}, headers=headers
    )
    assert bad_cycle.status_code == 422

    created = api_client.post(
        "/api/v1/users",
        json={
            "name": "alice",
            "quota_bytes": 1024,
            "quota_cycle": "monthly",
            "note": "primary",
            "expires_at": (utcnow() + timedelta(days=30)).isoformat(),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    user = payload["user"]
    user_id = user["id"]
    assert payload["applied"] is True
    assert payload["revision"] == "revision-1"
    assert payload["password_once"]
    assert user["has_subscription"] is True
    assert payload["subscription"]["formats"][0]["id"] == "ostium"

    duplicate = api_client.post("/api/v1/users", json={"name": "alice"}, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "name_taken"

    # With no collector there is no pending usage and no online state.
    no_stats = api_client.get(f"/api/v1/users/{user_id}").json()
    assert no_stats["pending_bytes"] == 0
    assert no_stats["user"]["online"] is False

    stats = FakeStats(user_id, "alice")
    api_client.app.state.services.stats = stats  # type: ignore[assignment]
    detail = api_client.get(f"/api/v1/users/{user_id}").json()
    assert detail["pending_bytes"] == 30
    assert detail["user"]["online"] is True

    updated = api_client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "enabled": False,
            "quota_bytes": 2048,
            "quota_cycle": "total",
            "note": "changed",
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["user"]["enabled"] is False
    assert updated.json()["user"]["quota_bytes"] == 2048

    reenabled = api_client.patch(
        f"/api/v1/users/{user_id}", json={"enabled": True}, headers=headers
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["user"]["disabled_reason"] is None

    note_only = api_client.patch(
        f"/api/v1/users/{user_id}", json={"note": "only note"}, headers=headers
    )
    assert note_only.status_code == 200
    assert note_only.json()["user"]["note"] == "only note"

    rotated_without_sub = api_client.post(
        f"/api/v1/users/{user_id}/rotate", json={}, headers=headers
    )
    assert rotated_without_sub.status_code == 200
    assert "subscription_token" not in rotated_without_sub.json()

    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(
            "UPDATE proxy_users SET subscription_token_enc=NULL WHERE id=?", (user_id,)
        )
        connection.commit()
    regenerated = api_client.get(f"/api/v1/users/{user_id}/subscription")
    assert regenerated.status_code == 200
    assert regenerated.json()["token"]

    sub_before = api_client.get(f"/api/v1/users/{user_id}/subscription")
    assert sub_before.status_code == 200
    assert sub_before.json()["links"]
    rotated = api_client.post(f"/api/v1/users/{user_id}/subscription/rotate", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["token"] != sub_before.json()["token"]

    credentials = api_client.post(
        f"/api/v1/users/{user_id}/rotate",
        json={"rotate_subscription": True},
        headers=headers,
    )
    assert credentials.status_code == 200
    assert credentials.json()["subscription_rotated"] is True
    assert credentials.json()["subscription_token"]

    exported = api_client.get(f"/api/v1/users/{user_id}/export")
    assert exported.status_code == 200
    assert exported.json()["format"] == "ostium-profile"

    usage = api_client.get(f"/api/v1/users/{user_id}/usage?days=9999")
    assert usage.status_code == 200
    assert usage.json()["series"] == []

    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(
            "INSERT INTO traffic_user_daily (id,user_id,day,uplink,downlink) VALUES (?,?,?,?,?)",
            ("traffic-1", user_id, utcnow().date().isoformat(), 12, 34),
        )
        connection.commit()
    series = api_client.get(f"/api/v1/users/{user_id}/usage?days=7").json()
    assert series["series"][-1]["up"] == 12
    assert series["today"]["down"] == 34

    reset = api_client.post(f"/api/v1/users/{user_id}/reset-usage", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["user"]["used_bytes"] == 0

    overview = api_client.get("/api/v1/subscriptions").json()
    assert overview["subscriptions"][0]["has_token"] is True
    assert overview["subscriptions"][0]["links"]


def test_user_not_found_and_engine_errors(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    assert api_client.get("/api/v1/users/missing").status_code == 404
    assert api_client.patch("/api/v1/users/missing", json={}, headers=headers).status_code == 404
    assert api_client.delete("/api/v1/users/missing", headers=headers).status_code == 404
    assert (
        api_client.post("/api/v1/users/missing/rotate", json={}, headers=headers).status_code == 404
    )

    async def unreachable(session: object) -> dict:
        raise EngineError("core down", "core_unreachable", 503)

    api_client.app.state.services.engine.apply_server = unreachable  # type: ignore[method-assign]
    created = api_client.post("/api/v1/users", json={"name": "bob"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["applied"] is False

    async def rejected(session: object) -> dict:
        raise EngineError("bad config", "engine_check_failed", 422)

    api_client.app.state.services.engine.apply_server = rejected  # type: ignore[method-assign]
    failed = api_client.post("/api/v1/users", json={"name": "carol"}, headers=headers)
    assert failed.status_code == 422
    assert failed.json()["code"] == "engine_check_failed"


def test_subscription_rate_limit(api_client: TestClient, monkeypatch) -> None:
    from ostium.api import routes_subscriptions

    monkeypatch.setattr(routes_subscriptions.LIMITER, "allow", lambda *args: False)
    response = api_client.get("/sub/whatever?format=ostium")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_bulk_actions(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    ids = []
    for name in ("a", "b", "c"):
        response = api_client.post("/api/v1/users", json={"name": name}, headers=headers)
        ids.append(response.json()["user"]["id"])

    missing = api_client.post(
        "/api/v1/users/bulk", json={"action": "enable", "ids": ["nope"]}, headers=headers
    )
    assert missing.status_code == 404

    disabled = api_client.post(
        "/api/v1/users/bulk", json={"action": "disable", "ids": ids[:2]}, headers=headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["count"] == 2
    assert (
        api_client.get("/api/v1/subscriptions").json()["subscriptions"][0]["status"] == "disabled"
    )

    enabled = api_client.post(
        "/api/v1/users/bulk", json={"action": "enable", "ids": ids[:2]}, headers=headers
    )
    assert enabled.status_code == 200

    rotated = api_client.post(
        "/api/v1/users/bulk", json={"action": "rotate", "ids": ids[:1]}, headers=headers
    )
    assert rotated.status_code == 200

    exported = api_client.post(
        "/api/v1/users/bulk", json={"action": "export", "ids": ids}, headers=headers
    )
    assert exported.status_code == 200
    assert "applied" not in exported.json()

    deleted = api_client.post(
        "/api/v1/users/bulk", json={"action": "delete", "ids": ids}, headers=headers
    )
    assert deleted.status_code == 200
    assert api_client.get("/api/v1/users").json()["total"] == 0


def test_inbound_management(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    listing = api_client.get("/api/v1/inbounds").json()["inbounds"]
    assert len(listing) == 4
    vless = next(item for item in listing if item["kind"] == "vless")
    assert vless["requires_certificate"] is False
    assert vless["params"]["public_key"]

    assert api_client.patch("/api/v1/inbounds/nope", json={}, headers=headers).status_code == 404
    assert (
        api_client.patch("/api/v1/inbounds/vless", json={"port": 8443}, headers=headers).status_code
        == 400
    )
    same_port = api_client.patch("/api/v1/inbounds/vless", json={"port": 443}, headers=headers)
    assert same_port.status_code == 200

    no_cert = api_client.patch(
        "/api/v1/inbounds/hysteria2", json={"enabled": True}, headers=headers
    )
    assert no_cert.status_code == 409
    assert no_cert.json()["code"] == "certificate_required"

    cert = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "inbound.example.com", "method": "self-signed"},
        headers=headers,
    ).json()["certificate"]
    enabled = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"enabled": True, "obfs_password": "obfs-secret"},
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["inbound"]["params"]["has_obfs"] is True
    assert enabled.json()["inbound"]["certificate"]["id"] == cert["id"]

    cleared = api_client.patch(
        "/api/v1/inbounds/hysteria2", json={"obfs_password": ""}, headers=headers
    )
    assert cleared.json()["inbound"]["params"]["has_obfs"] is False

    trojan = api_client.patch("/api/v1/inbounds/trojan", json={"enabled": True}, headers=headers)
    assert trojan.status_code == 200
    vless_after = api_client.get("/api/v1/inbounds").json()["inbounds"]
    assert next(item for item in vless_after if item["kind"] == "vless")["enabled"] is False

    vless_enabled = api_client.patch(
        "/api/v1/inbounds/vless", json={"enabled": True}, headers=headers
    )
    assert vless_enabled.status_code == 200
    trojan_after = api_client.get("/api/v1/inbounds").json()["inbounds"]
    assert next(item for item in trojan_after if item["kind"] == "trojan")["enabled"] is False

    wrong_cert_kind = api_client.patch(
        "/api/v1/inbounds/vless", json={"certificate_id": cert["id"]}, headers=headers
    )
    assert wrong_cert_kind.status_code == 400
    missing_cert = api_client.patch(
        "/api/v1/inbounds/trojan", json={"certificate_id": "nope"}, headers=headers
    )
    assert missing_cert.status_code == 404

    reality = api_client.patch(
        "/api/v1/inbounds/vless",
        json={
            "reality_server_name": "www.cloudflare.com",
            "reality_handshake_server": "www.cloudflare.com",
            "reality_handshake_port": 8443,
        },
        headers=headers,
    )
    assert reality.status_code == 200
    params = reality.json()["inbound"]["params"]
    assert params["server_name"] == "www.cloudflare.com"
    assert params["handshake_port"] == 8443

    bad_rotate = api_client.post("/api/v1/inbounds/trojan/reality-keys", headers=headers)
    assert bad_rotate.status_code == 400
    before = api_client.get("/api/v1/inbounds").json()["inbounds"]
    old_key = next(item for item in before if item["kind"] == "vless")["params"]["public_key"]
    rotated = api_client.post("/api/v1/inbounds/vless/reality-keys", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["params"]["public_key"] != old_key


def test_inbound_engine_soft_failure(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    async def unreachable(session: object) -> dict:
        raise EngineError("core down", "core_unreachable", 503)

    api_client.app.state.services.engine.apply_server = unreachable  # type: ignore[method-assign]
    response = api_client.patch(
        "/api/v1/inbounds/vless", json={"enabled": True}, headers=_headers(session_token)
    )
    assert response.status_code == 200
    assert response.json()["applied"] is False

    async def rejected(session: object) -> dict:
        raise EngineError("bad config", "engine_check_failed", 422)

    api_client.app.state.services.engine.apply_server = rejected  # type: ignore[method-assign]
    fatal = api_client.patch(
        "/api/v1/inbounds/vless", json={"enabled": True}, headers=_headers(session_token)
    )
    assert fatal.status_code == 422

    # A missing inbound row after kind validation is a 404.
    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute("DELETE FROM inbounds WHERE kind='vless'")
        connection.commit()
    gone = api_client.patch(
        "/api/v1/inbounds/vless", json={"enabled": True}, headers=_headers(session_token)
    )
    assert gone.status_code == 404
