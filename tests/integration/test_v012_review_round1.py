"""Regression tests for the v0.1.2 first full-review round."""

from __future__ import annotations

import asyncio
import socket
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from ostium.config import Role, Settings
from ostium.db.models import Alert, ProxyUser, RuleSet
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.engine.singbox.v2ray_stats import StatsUnavailable
from ostium.services.backup import create_backup, restore_backup
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.netguard import UnsafeUrlError, _pin_dns, post_limited
from ostium.services.rules import update_rule_set
from ostium.services.settings import get_setting
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user, decrypt_password
from ostium.util.security import CryptoError
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


async def _schema(settings: Settings):
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    return engine, create_session_factory(engine), SecretStore.from_data_dir(settings.data_dir)


def test_stats_outage_still_enforces_and_raises_critical_alert(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, factory, _store = await _schema(settings)
        bus = EventBus()
        collector = StatsCollector(settings=settings, session_factory=factory, bus=bus)

        async def unavailable(timeout: float = 5.0) -> dict[str, tuple[int, int]]:
            raise StatsUnavailable("collector is down")

        enforced: list[bool] = []

        async def enforce() -> None:
            enforced.append(True)

        collector.client.query_users = unavailable  # type: ignore[method-assign]
        collector.enforce_quotas = enforce  # type: ignore[method-assign]
        # The next tick is the sixth, which is when quota enforcement runs.
        collector._tick = 5
        collector._stats_down_since = time.monotonic() - 301
        await collector.tick()
        assert enforced == [True]

        async with factory() as session:
            rows = (
                (await session.execute(select(Alert).where(Alert.code.like("stats_unavailable%"))))
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].level == "critical"
        await engine.dispose()

    asyncio.run(_run())


def test_missing_master_key_fails_closed_only_when_ciphertext_exists(tmp_path: Path) -> None:
    async def _run() -> None:
        encrypted = _settings(tmp_path, "encrypted")
        engine, factory, store = await _schema(encrypted)
        async with factory() as session:
            await create_user(session, store, name="alice")
            await session.commit()
        await engine.dispose()
        encrypted.paths.master_key_path.unlink()
        with pytest.raises(CryptoError, match="master key is missing"):
            SecretStore.from_data_dir(encrypted.data_dir)

        fresh = _settings(tmp_path, "fresh")
        engine, _factory, _store = await _schema(fresh)
        await engine.dispose()
        fresh.paths.master_key_path.unlink()
        recreated = SecretStore.from_data_dir(fresh.data_dir)
        assert fresh.paths.master_key_path.is_file()
        assert recreated is not None

    asyncio.run(_run())


def test_streamed_v2_backup_round_trips_across_directories(tmp_path: Path) -> None:
    async def _run() -> None:
        source = _settings(tmp_path, "source")
        engine, factory, store = await _schema(source)
        async with factory() as session:
            await create_user(session, store, name="alice")
            await session.commit()
        await engine.dispose()

        created = create_backup(source, password="long-passphrase")
        payload = Path(created["path"]).read_bytes()
        assert payload.startswith(b"OSTB2")
        assert created["encrypted"] is True

        target = _settings(tmp_path, "target")
        restored = restore_backup(target, Path(created["path"]), password="long-passphrase")
        assert restored["restored"] is True
        assert target.paths.master_key_path.is_file()
        with sqlite3.connect(target.paths.db_path) as connection:
            row = connection.execute("SELECT id FROM proxy_users WHERE name='alice'").fetchone()
        assert row is not None
        # The restored key must still decrypt the restored credential.
        target_store = SecretStore.from_data_dir(target.data_dir)
        engine, factory, _store = await _schema(target)
        async with factory() as session:
            user = await session.get(ProxyUser, row[0])
            assert user is not None
            assert decrypt_password(user, target_store)
        await engine.dispose()

    asyncio.run(_run())


def test_pin_dns_uses_only_validated_addresses(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    original = socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(str(host))
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with _pin_dns("example.com", ("127.0.0.1",)):
        socket.getaddrinfo("example.com", 443)
    assert calls and calls[0] == "127.0.0.1"

    async def _metadata() -> None:
        with pytest.raises(UnsafeUrlError):
            await post_limited("http://169.254.169.254/hook", content=b"{}")

    asyncio.run(_metadata())


def test_rule_set_html_page_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    settings = _settings(tmp_path)

    async def _run() -> None:
        engine, factory, _store = await _schema(settings)
        async with factory() as session:
            rule_set = RuleSet(name="ads", url="https://example.com/ads.srs", format="binary")
            session.add(rule_set)
            await session.commit()
            with respx.mock:
                respx.get("https://example.com/ads.srs").mock(
                    return_value=httpx.Response(200, content=b"<!doctype html><html>oops")
                )
                result = await update_rule_set(session, settings, rule_set)
                await session.commit()
            assert result["updated"] is False
            assert "HTML" in (rule_set.last_error or "")
            assert rule_set.path is None
        await engine.dispose()

    asyncio.run(_run())


def test_webhook_secret_is_encrypted_at_rest(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = {"X-CSRF-Token": token}
    response = api_client.patch(
        "/api/v1/settings",
        json={"webhook_url": "https://hooks.example.com/x", "webhook_secret": "top-secret"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    services = api_client.app.state.services

    async def _read() -> None:
        async with services.session_factory() as session:
            raw = await get_setting(session, "webhook_secret")
            assert isinstance(raw, str)
            assert raw.startswith("v1.")
            assert "top-secret" not in raw
            assert (
                services.store.decrypt(
                    raw, table="settings", record_id="webhook_secret", field="secret"
                )
                == "top-secret"
            )

    asyncio.run(_read())


def test_narrow_scope_tokens_require_a_legacy_scope(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    response = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "narrow-only", "scopes": ["subscription:read"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_scopes"
    assert token is not None
