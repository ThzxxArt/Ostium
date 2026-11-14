"""Regression tests for v0.1.2 state convergence (P0-01/P0-02)."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

from ostium.config import Role, Settings
from ostium.db.models import ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.engine.manager import EngineManager
from ostium.engine.singbox.config import (
    CONFIG_POLICY_VERSION,
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_server_config,
    config_digest,
)
from ostium.engine.singbox.supervisor import CoreSupervisor
from ostium.services.crypto import SecretStore
from ostium.services.enforcement import read_enforcement, write_enforcement
from ostium.services.events import EventBus
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user, reset_usage
from ostium.util.time import utcnow


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(tmp_path / "sing-box"),
        proxy_ports=[443, 8388],
        dev=True,
    )
    value.paths.ensure()
    return value


async def _setup(tmp_path: Path):
    settings = _settings(tmp_path)
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    return settings, engine, factory, store


def _server_config() -> dict:
    return build_server_config(
        ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="vless",
                    enabled=True,
                    listen="127.0.0.1",
                    port=443,
                    reality=RealitySpec(private_key="private", short_id="short"),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password="ss",
                ),
                UserCredential(
                    name="bob",
                    uuid="6f1c5f2e-7f37-4f7a-9a5e-3f4d5c6b7a80",
                    password="pw2",
                    ss_password="ss2",
                ),
            ],
            clash_secret="secret",
            enable_v2ray_api=False,
        )
    )


def test_quota_apply_failure_keeps_pending_and_enforcement(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            user, _password, _token = await create_user(
                session, store, name="alice", quota_bytes=100
            )
            user.used_bytes = 100
            await session.commit()
            user_id = user.id

        attempts: list[list[str]] = []

        async def failing(names: list[str]) -> None:
            attempts.append(list(names))
            raise RuntimeError("core is down")

        collector = StatsCollector(
            settings=settings, session_factory=factory, bus=EventBus(), on_quota=failing
        )
        await collector.enforce_quotas()

        async with factory() as session:
            refreshed = await session.get(ProxyUser, user_id)
            assert refreshed is not None
            assert refreshed.enabled is False
            assert refreshed.disabled_reason == "quota_exceeded"

        # A failed apply must not erase the revocation: the collector retries it
        # and the core reads the same policy on its next start.
        assert "alice" in collector._pending_disable
        assert read_enforcement(settings.paths.enforcement_path) == {"alice"}

        async def succeeding(names: list[str]) -> None:
            attempts.append(list(names))

        collector.on_quota = succeeding
        await collector.enforce_quotas()
        assert not collector._pending_disable
        assert attempts == [["alice"], ["alice"]]
        await engine.dispose()

    asyncio.run(_run())


def test_reset_usage_discards_unflushed_samples(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            await session.commit()
            user_id = user.id

        collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
        collector._pending[user_id].up = 4096
        collector._pending[user_id].down = 8192
        async with factory() as session:
            user = await session.get(ProxyUser, user_id)
            assert user is not None
            await reset_usage(session, user, stats=collector)
            await session.commit()

        assert collector.pending_bytes(user_id) == 0
        assert user_id not in collector._alerted
        await engine.dispose()

    asyncio.run(_run())


def test_server_spec_filters_expired_and_exhausted_users(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        now = utcnow()
        async with factory() as session:
            await create_user(session, store, name="expired", expires_at=now - timedelta(hours=1))
            quota_user, _password, _token = await create_user(
                session, store, name="exhausted", quota_bytes=100
            )
            quota_user.used_bytes = 100
            await create_user(session, store, name="active")
            await session.commit()

        manager = EngineManager(settings, factory, store, EventBus())
        collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
        manager.stats = collector
        async with factory() as session:
            spec = await manager._server_spec(session)
        assert [item.name for item in spec.users] == ["active"]
        await engine.dispose()

    asyncio.run(_run())


def test_core_start_strips_users_revoked_in_database(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        config = _server_config()
        settings.paths.last_good_path.write_text(json.dumps(config), encoding="utf-8")
        settings.paths.last_good_meta_path.write_text(
            json.dumps({"policy_version": CONFIG_POLICY_VERSION, "allow_lan": False}),
            encoding="utf-8",
        )
        write_enforcement(settings.paths.enforcement_path, {"bob"})
        supervisor = CoreSupervisor(settings)
        captured: list[dict] = []

        async def fake_spawn() -> None:
            captured.append(json.loads(settings.paths.last_good_path.read_text()))

        supervisor._spawn = fake_spawn  # type: ignore[method-assign]
        await supervisor.start()
        assert len(captured) == 1
        users = captured[0]["inbounds"][0]["users"]
        assert [item["name"] for item in users] == ["alice"]
        # The sanitized file is persisted, so a later restart cannot resurrect
        # the revoked user even if the control plane is down.
        stored = json.loads(settings.paths.last_good_path.read_text())
        assert [item["name"] for item in stored["inbounds"][0]["users"]] == ["alice"]

    asyncio.run(_run())


def test_core_refuses_stale_server_policy(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        config = _server_config()
        settings.paths.last_good_path.write_text(json.dumps(config), encoding="utf-8")
        # Simulates last-good from 0.1.0/0.1.1: no policy_version recorded.
        settings.paths.last_good_meta_path.write_text(
            json.dumps({"allow_lan": False}), encoding="utf-8"
        )
        supervisor = CoreSupervisor(settings)
        spawned = False

        async def fake_spawn() -> None:
            nonlocal spawned
            spawned = True

        supervisor._spawn = fake_spawn  # type: ignore[method-assign]
        await supervisor.start()
        assert spawned is False
        assert "predates the current security policy" in (supervisor.status().last_error or "")

    asyncio.run(_run())


def test_reconcile_server_applies_once_per_digest(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        manager = EngineManager(settings, factory, store, EventBus())
        config = _server_config()
        applied: list[str] = []

        async def preview(session):  # type: ignore[no-untyped-def]
            return config

        async def fake_apply(session):  # type: ignore[no-untyped-def]
            applied.append("apply")
            manager._last_applied["server"] = config_digest(config)
            return {}

        manager.server_preview = preview  # type: ignore[method-assign]
        manager.apply_server = fake_apply  # type: ignore[method-assign]
        assert await manager.reconcile_server(None, force=True) is True
        assert await manager.reconcile_server(None) is False
        assert applied == ["apply"]
        await engine.dispose()

    asyncio.run(_run())


def test_database_users_are_disabled_before_the_next_tick(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            user.expires_at = utcnow() - timedelta(seconds=1)
            await session.commit()

        manager = EngineManager(settings, factory, store, EventBus())
        async with factory() as session:
            spec = await manager._server_spec(session)
        assert spec.users == []
        await engine.dispose()

    asyncio.run(_run())
