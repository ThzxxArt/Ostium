"""Regression tests for the v0.1.2 second full-review round."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from ostium.api.deps import Services
from ostium.cli.main import app as cli_app
from ostium.config import Role, Settings
from ostium.db.models import ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.engine.manager import EngineError
from ostium.engine.singbox.v2ray_stats import StatsUnavailable
from ostium.engine.singbox.validate import validate_config
from ostium.services import netguard
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.settings import get_setting
from ostium.services.stats import StatsCollector, UserUsage
from tests.conftest import csrf, setup_admin


def _settings(tmp_path: Path, name: str = "data") -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / name,
        config_dir=tmp_path / f"{name}-config",
        state_dir=tmp_path / f"{name}-state",
        core_token_file=tmp_path / name / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


async def _schema(settings: Settings):  # type: ignore[no-untyped-def]
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    return engine, create_session_factory(engine), SecretStore.from_data_dir(settings.data_dir)


def test_inbound_port_apply_failure_keeps_the_approved_port(
    api_client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed apply must not un-approve a port the database already committed.

    ``_apply_server`` commits before contacting the core.  Reverting
    ``proxy_ports`` afterwards left the committed inbound on a port the core
    validator rejected, so every later reconcile failed with
    ``port_not_allowed`` and the server never converged again.
    """

    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    services = api_client.app.state.services

    async def fail(_session: object) -> dict[str, object]:
        raise EngineError("sing-box check failed", "engine_check_failed", 422)

    monkeypatch.setattr(services.engine, "apply_server", fail)
    response = api_client.patch("/api/v1/inbounds/vless", json={"port": 14444}, headers=headers)
    assert response.status_code == 422, response.text
    assert 14444 in services.settings.proxy_ports

    async def _preview() -> dict[str, object]:
        async with services.session_factory() as session:
            return await services.engine.server_preview(session)

    config = asyncio.run(_preview())
    # This is the exact validation the reconciler performs on its next tick.
    validate_config(
        config,
        role=Role.SERVER,
        allowed_ports=set(services.settings.proxy_ports),
        allowed_paths=[settings.paths.data_dir, settings.paths.certs_dir],
    )


def test_fetch_limited_resolves_dns_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, threading.Thread] = {}

    def fake_resolve(url: str, *, allow_private: bool = False) -> netguard.ResolvedTarget:
        seen["thread"] = threading.current_thread()
        return netguard.ResolvedTarget(url, "example.com", 443, ("93.184.216.34",))

    monkeypatch.setattr(netguard, "resolve_remote_url", fake_resolve)

    async def _run() -> netguard.FetchedPayload:
        with respx.mock:
            respx.get("https://example.com/sub").mock(
                return_value=httpx.Response(200, content=b"ok")
            )
            return await netguard.fetch_limited("https://example.com/sub", max_bytes=1024)

    result = asyncio.run(_run())
    assert result.content == b"ok"
    assert seen["thread"] is not threading.main_thread()


def test_services_proxy_is_constructed_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ostium.api import deps

    calls: list[Settings] = []

    class Stub:
        pass

    def fake_proxy(value: Settings) -> Stub:
        calls.append(value)
        return Stub()

    monkeypatch.setattr(deps, "system_proxy", fake_proxy)
    services = Services(
        settings=settings,
        session_factory=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        bus=None,  # type: ignore[arg-type]
        jobs=None,  # type: ignore[arg-type]
        engine=None,  # type: ignore[arg-type]
        stats=None,
        clash=None,  # type: ignore[arg-type]
    )
    first = services.proxy
    second = services.proxy
    assert first is second
    assert len(calls) == 1


def test_disconnect_failure_clears_the_paused_intent(
    client_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_admin(client_api, role="client")
    headers = {"X-CSRF-Token": csrf(client_api)}
    services = client_api.app.state.services

    class FailingProxy:
        def status(self) -> dict[str, object]:
            return {"enabled": True}

        def disable(self) -> dict[str, object]:
            raise RuntimeError("gsettings is unavailable")

    monkeypatch.setattr(services, "proxy_manager", FailingProxy())
    response = client_api.post("/api/v1/system/disconnect", headers=headers)
    assert response.status_code == 502, response.text
    assert services.client_paused is False
    assert services.watchdog_suspended is False

    async def _paused() -> object:
        async with services.session_factory() as session:
            return await get_setting(session, "client_paused", None)

    assert asyncio.run(_paused()) is False


def test_add_user_returns_the_password_when_apply_fails(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    services = api_client.app.state.services

    async def fail(_session: object) -> dict[str, object]:
        raise EngineError("invalid configuration", "engine_check_failed", 422)

    monkeypatch.setattr(services.engine, "apply_server", fail)
    response = api_client.post("/api/v1/users", json={"name": "alice"}, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["applied"] is False
    assert body["warning"]
    assert body["password_once"]
    assert body["subscription"]["formats"]

    async def _exists() -> bool:
        async with services.session_factory() as session:
            row = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == "alice"))
            ).scalar_one_or_none()
            return row is not None

    assert asyncio.run(_exists())


def test_rotate_user_returns_the_new_token_when_apply_fails(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    services = api_client.app.state.services
    created = api_client.post("/api/v1/users", json={"name": "bob"}, headers=headers)
    assert created.status_code == 201, created.text
    user_id = created.json()["user"]["id"]

    async def fail(_session: object) -> dict[str, object]:
        raise EngineError("invalid configuration", "engine_check_failed", 422)

    monkeypatch.setattr(services.engine, "apply_server", fail)
    response = api_client.post(
        f"/api/v1/users/{user_id}/rotate",
        json={"rotate_subscription": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is False
    assert body["subscription_token"]


def test_stats_outage_marks_users_offline(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, factory, _store = await _schema(settings)
        collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
        collector.usage["u1"] = UserUsage(user_id="u1", name="alice", online=True)
        collector._stats_down_since = time.monotonic() - 61
        await collector._record_stats_unavailable(StatsUnavailable("collector is down"))
        assert collector.usage["u1"].online is False
        await engine.dispose()

    asyncio.run(_run())


def test_background_alert_tasks_are_referenced_until_completion() -> None:
    from ostium.services import audit as audit_module

    async def _run() -> None:
        started = asyncio.Event()
        released = asyncio.Event()

        async def work() -> None:
            started.set()
            await released.wait()

        audit_module._spawn(work())
        await started.wait()
        assert audit_module._BACKGROUND_TASKS
        released.set()
        await asyncio.sleep(0.05)
        assert not audit_module._BACKGROUND_TASKS

    asyncio.run(_run())


def test_init_public_ui_enables_secure_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    result = CliRunner().invoke(
        cli_app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--password",
            "verysecret123",
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--public-ui",
            "--domain",
            "vpn.example.com",
        ],
    )
    assert result.exit_code == 0, result.output
    loaded = Settings.load()
    assert loaded.public_ui is True
    assert loaded.secure_cookies is True


def test_public_ui_disable_without_marker_keeps_the_cookie_policy(
    api_client: TestClient, settings: Settings
) -> None:
    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    # Simulate a legacy/CLI-enabled Public UI that predates the marker.
    settings.public_ui = True
    settings.secure_cookies = True
    response = api_client.post(
        "/api/v1/settings/public-ui", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert settings.secure_cookies is True


def test_fresh_create_all_matches_the_migration_graph(tmp_path: Path) -> None:
    """A fresh install and an upgraded install must produce the same schema."""

    from alembic import command

    from ostium.db import session as session_module

    fresh = tmp_path / "fresh.db"

    async def _create() -> None:
        engine = create_engine(fresh)
        try:
            await create_schema(engine)
        finally:
            await engine.dispose()

    asyncio.run(_create())
    migrated = tmp_path / "migrated.db"
    command.upgrade(session_module._alembic_config(migrated), "head")

    def dump(path: Path) -> dict[str, tuple[list[tuple[object, ...]], list[tuple[object, ...]]]]:
        with sqlite3.connect(path) as connection:
            tables = sorted(
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
                )
            )
            result = {}
            for table in tables:
                columns = [
                    (row[1], row[2], row[3], row[5])
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                ]
                indexes = sorted(
                    (row[1], row[2])
                    for row in connection.execute(f'PRAGMA index_list("{table}")')
                    if not str(row[1]).startswith("sqlite_autoindex")
                )
                result[table] = (columns, indexes)
            return result

    assert dump(fresh) == dump(migrated)


def test_unknown_username_still_spends_password_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ostium.services import auth as auth_service

    settings = _settings(tmp_path)

    async def _run() -> None:
        engine, factory, _store = await _schema(settings)
        async with factory() as session:
            await auth_service.create_admin(session, username="admin", password="verysecret123")
            await session.commit()
            calls: list[str] = []
            original = auth_service.verify_password

            def record(password: str, hashed: str) -> bool:
                calls.append(password)
                return original(password, hashed)

            monkeypatch.setattr(auth_service, "verify_password", record)
            with pytest.raises(auth_service.AuthError):
                await auth_service.authenticate(
                    session,
                    settings,
                    username="nobody",
                    password="guess",
                    totp_code=None,
                    ip="127.0.0.1",
                )
            assert calls, "an unknown username must still run the password hash"
        await engine.dispose()

    asyncio.run(_run())


def test_tls_reload_plan_never_converts_a_plaintext_control_plane() -> None:
    from ostium.cli.main import _tls_reload_plan

    # A renewed inbound certificate must not turn an Nginx/SSH-tunnel control
    # plane into an HTTPS listener.
    assert _tls_reload_plan(tls_active=False, recovery=False, found=("c", "k")) == "skip"
    assert _tls_reload_plan(tls_active=True, recovery=False, found=("c", "k")) == "reload"
    assert _tls_reload_plan(tls_active=False, recovery=True, found=("c", "k")) == "recover"
    assert _tls_reload_plan(tls_active=False, recovery=True, found=None) == "recover"
    assert _tls_reload_plan(tls_active=True, recovery=False, found=None) == "skip"


def test_plan_tls_reload_covers_plaintext_recovery_and_reload() -> None:
    from ostium.cli.main import _plan_tls_reload

    found = ("/tmp/fullchain.pem", "/tmp/privkey.pem")
    plaintext = _plan_tls_reload(ssl_certfile=None, ssl_keyfile=None, recovery=None, found=found)
    assert plaintext.skip is True
    assert plaintext.message is None

    reloaded = _plan_tls_reload(
        ssl_certfile="/old/cert.pem", ssl_keyfile="/old/key.pem", recovery=None, found=found
    )
    assert reloaded.skip is False
    assert (reloaded.certfile, reloaded.keyfile) == found
    assert reloaded.restore_recovery is False

    recovered = _plan_tls_reload(
        ssl_certfile=None,
        ssl_keyfile=None,
        recovery=("0.0.0.0", True, True),
        found=found,
    )
    assert recovered.restore_recovery is True
    assert recovered.message is not None

    pending = _plan_tls_reload(
        ssl_certfile=None,
        ssl_keyfile=None,
        recovery=("0.0.0.0", True, True),
        found=None,
    )
    assert pending.skip is True
    assert pending.message is not None

    nothing = _plan_tls_reload(ssl_certfile=None, ssl_keyfile=None, recovery=None, found=None)
    assert nothing.skip is True
    assert nothing.message is None


def test_public_ui_disable_converges_a_legacy_public_bind_to_loopback(
    api_client: TestClient, settings: Settings
) -> None:
    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    settings.public_ui = True
    settings.secure_cookies = True
    settings.host = "0.0.0.0"
    response = api_client.post(
        "/api/v1/settings/public-ui", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert settings.host == "127.0.0.1"
    # The persisted configuration must still pass the startup bind policy.
    settings.validate_bind()


def test_public_ui_disable_keeps_an_explicit_public_plaintext_bind(
    api_client: TestClient, settings: Settings
) -> None:
    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    settings.public_ui = True
    settings.secure_cookies = True
    settings.host = "0.0.0.0"
    settings.allow_insecure_bind = True
    response = api_client.post(
        "/api/v1/settings/public-ui", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert settings.host == "0.0.0.0"
    settings.validate_bind()


def test_public_ui_listener_always_sets_secure_cookies(
    api_client: TestClient, settings: Settings
) -> None:
    settings.public_ui = True
    settings.secure_cookies = False
    api_client.cookies.clear()
    response = api_client.get("/healthz")
    assert "Strict-Transport-Security" in response.headers
    cookie_header = response.headers.get("set-cookie", "")
    assert "ostium_csrf=" in cookie_header
    assert "Secure" in cookie_header
