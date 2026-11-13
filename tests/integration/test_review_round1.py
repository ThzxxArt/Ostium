from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from ostium.api import routes_profiles
from ostium.api.ratelimit import SlidingWindowLimiter
from ostium.services.netguard import UnsafeUrlError, fetch_limited, validate_target_host
from ostium.services.profiles import ProfileError
from tests.conftest import csrf

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=pub&sid=55e1651e#HK"
)


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_guarded_fetch_revalidates_redirects_and_size() -> None:
    with respx.mock:
        respx.get("http://93.184.216.34/start").mock(
            return_value=httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        )
        with pytest.raises(UnsafeUrlError, match="not allowed"):
            asyncio.run(
                fetch_limited(
                    "http://93.184.216.34/start",
                    allow_private=False,
                    max_bytes=1024,
                )
            )

    with respx.mock:
        respx.get("http://93.184.216.34/ok").mock(return_value=httpx.Response(200, content=b"ok"))
        payload = asyncio.run(
            fetch_limited("http://93.184.216.34/ok", allow_private=False, max_bytes=8)
        )
        assert payload.status_code == 200
        assert payload.text == "ok"

    with respx.mock:
        respx.get("http://93.184.216.34/hop").mock(
            return_value=httpx.Response(302, headers={"location": "/final"})
        )
        respx.get("http://93.184.216.34/final").mock(
            return_value=httpx.Response(200, content=b"done")
        )
        hopped = asyncio.run(
            fetch_limited("http://93.184.216.34/hop", allow_private=False, max_bytes=8)
        )
        assert hopped.url == "http://93.184.216.34/final"
        assert hopped.text == "done"

    with respx.mock:
        respx.get("http://93.184.216.34/large").mock(
            return_value=httpx.Response(200, content=b"x" * 32)
        )
        with pytest.raises(ValueError, match="byte limit"):
            asyncio.run(
                fetch_limited(
                    "http://93.184.216.34/large",
                    allow_private=False,
                    max_bytes=8,
                )
            )
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(fetch_limited("http://93.184.216.34/ok", allow_private=False, max_bytes=0))
    with pytest.raises(UnsafeUrlError, match="empty"):
        validate_target_host("  ")

    assert validate_target_host("93.184.216.34") == "93.184.216.34"
    for blocked in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "localhost", "x.local"):
        with pytest.raises(UnsafeUrlError):
            validate_target_host(blocked)


def test_rule_set_rejects_metadata_target_and_normalises_names(
    api_client: TestClient,
) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text

    blocked = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "meta", "url": "http://169.254.169.254/latest/meta-data"},
        headers=_headers(token),
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "invalid_rule_set"

    created = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "ads", "url": "https://rules.example.com/ads.srs"},
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    duplicate = api_client.post(
        "/api/v1/rule-sets",
        json={"name": " ads ", "url": "https://rules.example.com/other.srs"},
        headers=_headers(token),
    )
    assert duplicate.status_code == 409


def test_profile_import_blocks_redirect_to_metadata(client_api: TestClient) -> None:
    token = csrf(client_api)
    response = client_api.post(
        "/api/v1/setup",
        json={
            "role": "client",
            "username": "admin",
            "password": "verysecret123",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text

    with respx.mock:
        respx.get("http://93.184.216.34/sub").mock(
            return_value=httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        )
        imported = client_api.post(
            "/api/v1/profiles",
            json={"name": "evil", "url": "http://93.184.216.34/sub"},
            headers=_headers(token),
        )
    assert imported.status_code == 400
    assert imported.json()["code"] == "unsafe_url"


def test_manual_profile_refresh_persists_last_error(
    client_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = csrf(client_api)
    response = client_api.post(
        "/api/v1/setup",
        json={
            "role": "client",
            "username": "admin",
            "password": "verysecret123",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    created = client_api.post(
        "/api/v1/profiles",
        json={"name": "HK", "text": VLESS},
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile"]["id"]

    async def failing(session, store, profile):  # type: ignore[no-untyped-def]
        profile.last_refresh_error = "upstream exploded"
        await session.flush()
        raise ProfileError("upstream exploded", "refresh_failed", 502)

    monkeypatch.setattr(routes_profiles, "refresh_profile", failing)
    refreshed = client_api.post(f"/api/v1/profiles/{profile_id}/refresh", headers=_headers(token))
    assert refreshed.status_code == 502
    listed = client_api.get("/api/v1/profiles")
    stored = next(item for item in listed.json()["profiles"] if item["id"] == profile_id)
    assert stored["last_refresh_error"] == "upstream exploded"


def test_subscription_overview_handles_user_without_endpoints(
    api_client: TestClient,
) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    assert (
        api_client.patch(
            "/api/v1/inbounds/vless",
            json={"enabled": False},
            headers=_headers(token),
        ).status_code
        == 200
    )
    created = api_client.post("/api/v1/users", json={"name": "alice"}, headers=_headers(token))
    assert created.status_code == 201, created.text

    overview = api_client.get("/api/v1/subscriptions")
    assert overview.status_code == 200, overview.text
    assert overview.json()["subscriptions"][0]["links"] == []


def test_enabling_inbound_detects_tcp_port_conflict(api_client: TestClient) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    headers = _headers(token)
    assert (
        api_client.patch(
            "/api/v1/inbounds/vless", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )
    assert (
        api_client.patch(
            "/api/v1/inbounds/shadowsocks", json={"port": 443}, headers=headers
        ).status_code
        == 200
    )
    assert (
        api_client.patch(
            "/api/v1/inbounds/shadowsocks", json={"enabled": True}, headers=headers
        ).status_code
        == 200
    )
    conflict = api_client.patch("/api/v1/inbounds/vless", json={"enabled": True}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "port_conflict"


def test_settings_can_clear_optional_values_and_rejects_bad_switches(
    api_client: TestClient,
) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    headers = _headers(token)

    assert (
        api_client.patch(
            "/api/v1/settings",
            json={
                "public_base_url": "https://edge.example.com",
                "acme_email": "ops@example.com",
                "webhook_url": "https://hooks.example.com/x",
                "webhook_secret": "secret",
            },
            headers=headers,
        ).status_code
        == 200
    )
    cleared = api_client.patch(
        "/api/v1/settings",
        json={
            "public_base_url": None,
            "acme_email": None,
            "webhook_url": None,
            "webhook_secret": None,
        },
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    reread = api_client.get("/api/v1/settings").json()
    assert reread["general"]["public_base_url"] is None
    assert reread["general"]["acme_email"] is None
    assert reread["notifications"]["webhook_url"] is None
    assert reread["notifications"]["has_webhook_secret"] is False

    assert (
        api_client.patch(
            "/api/v1/settings", json={"routing_mode": "bogus"}, headers=headers
        ).status_code
        == 400
    )
    assert (
        api_client.patch(
            "/api/v1/settings", json={"log_level": "verbose"}, headers=headers
        ).status_code
        == 400
    )
    assert (
        api_client.patch(
            "/api/v1/settings", json={"trusted_hosts": ["*"]}, headers=headers
        ).status_code
        == 400
    )


def test_rate_limiter_cleans_idle_keys() -> None:
    limiter = SlidingWindowLimiter(max_window=0.0)
    for index in range(700):
        assert limiter.allow(f"key-{index}", 60, 60.0)
    # Every 512th call performs cleanup; with max_window=0 the previously idle
    # buckets are dropped instead of accumulating forever.
    for index in range(512):
        limiter.allow(f"new-{index}", 60, 60.0)
    assert len(limiter._events) < 600
    limiter.reset()
    assert limiter._events == {}


def test_duplicate_profile_names_still_get_unique_tags() -> None:
    from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
    from ostium.engine.singbox.config import namespace_endpoint_tags

    endpoint = Endpoint(
        tag="hk",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(server_name="sni", reality_public_key="pub", reality_short_id="sid"),
    )
    flattened, mapping = namespace_endpoint_tags(
        [("id-one", "same", [endpoint]), ("id-two", "same", [endpoint])]
    )
    assert len({item.tag for item in flattened}) == 2
    assert mapping[("id-one", "hk")] != mapping[("id-two", "hk")]


def test_core_watchdog_reloads_only_when_needed(settings) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from ostium.api.app import _watchdog_tick
    from ostium.services.events import EventBus

    class Client:
        def __init__(self) -> None:
            self.reloads = 0
            self.running = False

        async def status(self):
            return {"running": self.running}

        async def reload(self):
            self.reloads += 1
            self.running = True
            return {"running": True}

    client = Client()
    services = SimpleNamespace(
        settings=settings,
        engine=SimpleNamespace(client=client),
        bus=EventBus(),
        watchdog_suspended=False,
    )
    settings.auto_reconnect = True

    # No last-good configuration yet: do not touch the core.
    asyncio.run(_watchdog_tick(services))
    assert client.reloads == 0

    settings.paths.last_good_path.write_text("{}", encoding="utf-8")
    asyncio.run(_watchdog_tick(services))
    assert client.reloads == 1

    # Already running: no redundant reload.
    asyncio.run(_watchdog_tick(services))
    assert client.reloads == 1

    client.running = False
    services.watchdog_suspended = True
    asyncio.run(_watchdog_tick(services))
    assert client.reloads == 1

    services.watchdog_suspended = False
    settings.auto_reconnect = False
    asyncio.run(_watchdog_tick(services))
    assert client.reloads == 1


def test_automatic_backup_is_listed_and_restorable(api_client: TestClient) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    patched = api_client.patch(
        "/api/v1/settings", json={"auto_backup": True}, headers=_headers(token)
    )
    assert patched.status_code == 200, patched.text

    from ostium.api.app import _run_housekeeping

    services = api_client.app.state.services
    api_client.portal.call(_run_housekeeping, services)
    listed = api_client.get("/api/v1/backups", headers=_headers(token)).json()["backups"]
    automatic = [item for item in listed if item["filename"].startswith("ostium-auto-backup-")]
    assert automatic
    assert automatic[0]["exists"] is True


def test_backup_filename_cannot_escape_directory(api_client: TestClient) -> None:
    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "example.com",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    import sqlite3

    db_path = api_client.app.state.services.settings.paths.db_path
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO backups (id,filename,size,sha256,encrypted,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "evil-backup",
                "../../etc/passwd",
                0,
                "0" * 64,
                0,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    deleted = api_client.delete("/api/v1/backups/evil-backup", headers=_headers(token))
    assert deleted.status_code == 400
    assert deleted.json()["code"] == "invalid_backup"


def test_backup_restore_snapshot_contains_wal(tmp_path: Path) -> None:
    from ostium.services.backup import _sqlite_backup
    from tests.integration.test_backup_extended import _seed, _settings

    settings = _settings(tmp_path, "wal-snapshot")
    _seed(settings)
    import sqlite3

    connection = sqlite3.connect(settings.paths.db_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT OR REPLACE INTO settings(key,value_json,updated_at) VALUES (?,?,?)",
            ("marker", '"kept"', "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
        assert Path(f"{settings.paths.db_path}-wal").is_file()

        copy = tmp_path / "snapshot.db"
        _sqlite_backup(settings.paths.db_path, copy)
    finally:
        connection.close()

    with sqlite3.connect(copy) as snapshot:
        row = snapshot.execute("SELECT value_json FROM settings WHERE key='marker'").fetchone()
    assert row == ('"kept"',)
