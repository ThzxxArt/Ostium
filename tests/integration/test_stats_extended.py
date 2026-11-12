from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from ostium.config import Role, Settings
from ostium.db.models import ProxyUser, TrafficDaily
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.stats import (
    SpeedSample,
    StatsCollector,
    UserUsage,
    record_epoch,
    usage_series,
)
from ostium.services.users import create_user
from ostium.util.time import utcnow


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
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


def test_start_stop_and_error_logging(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        settings, engine, factory, _store = await _setup(tmp_path)
        bus = EventBus()
        collector = StatsCollector(
            settings=settings, session_factory=factory, bus=bus, interval=0.01
        )

        from ostium.engine.singbox.v2ray_stats import StatsUnavailable

        calls = {"count": 0}

        async def tick() -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise StatsUnavailable("not ready")
            if calls["count"] == 2:
                raise RuntimeError("boom")

        monkeypatch.setattr(collector, "tick", tick)
        await collector.start()
        await collector.start()  # idempotent
        await asyncio.sleep(0.08)
        await collector.stop()
        logs = bus.logs()
        assert any("V2Ray statistics unavailable" in item["message"] for item in logs)
        assert any("statistics tick failed" in item["message"] for item in logs)

        # A collector that never started can still be stopped.
        idle = StatsCollector(settings=settings, session_factory=factory, bus=bus)
        await idle.stop()
        await engine.dispose()

    asyncio.run(_run())


def test_tick_baseline_deltas_and_stale_state(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            await create_user(session, store, name="bob")
            await session.commit()
            user_id = user.id

        collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
        values = iter(
            [
                {"alice": (10, 20), "ghost": (1, 1)},
                {"alice": (30, 50), "bob": (5, 5)},
                {"alice": (0, 0), "bob": (5, 5)},
            ]
        )

        async def query() -> dict[str, tuple[int, int]]:
            try:
                return next(values)
            except StopIteration:
                return {"alice": (0, 0), "bob": (5, 5)}

        collector.client.query_users = query  # type: ignore[method-assign]
        await collector.tick()
        assert collector.usage == {}
        await collector.tick()
        usage = collector.usage[user_id]
        assert (usage.up, usage.down) == (20, 30)
        assert usage.online is True
        assert usage.last_seen
        assert collector.snapshot()["online"] == 1

        # Force stale timestamps so the next tick marks users offline.
        usage.last_seen = (utcnow() - timedelta(minutes=5)).isoformat()
        await collector.tick()
        assert usage.online is False

        # Counter reset is treated as a new epoch rather than a negative delta.
        await collector.tick()
        assert collector._pending[user_id].up == 20
        await collector.flush()
        await engine.dispose()

    asyncio.run(_run())


def test_flush_updates_daily_rows_and_publishes(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            await session.commit()
            user_id = user.id
            session.add(
                TrafficDaily(
                    user_id=user_id,
                    day=utcnow().date(),
                    uplink=1,
                    downlink=2,
                )
            )
            await session.commit()

        bus = EventBus()
        queue = await bus.subscribe()
        collector = StatsCollector(settings=settings, session_factory=factory, bus=bus)
        collector._pending[user_id].up = 10
        collector._pending[user_id].down = 20
        collector._pending["unknown"].up = 5
        collector._pending["zero"].up = 0
        collector.usage[user_id] = UserUsage(user_id=user_id, name="alice")
        await collector.flush()

        async with factory() as session:
            user = await session.get(ProxyUser, user_id)
            assert user is not None
            assert user.used_bytes == 30
            row = (
                await session.execute(select(TrafficDaily).where(TrafficDaily.user_id == user_id))
            ).scalar_one()
            assert (row.uplink, row.downlink) == (11, 22)
        event = queue.get_nowait()
        assert event["type"] == "stats.tick"
        assert event["data"]["users"][0]["up"] == 0

        await collector.flush()  # no pending: no-op path
        await engine.dispose()

    asyncio.run(_run())


def test_enforce_quotas_monthly_expiry_disabled_and_callback_error(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            monthly, _password, _token = await create_user(
                session, store, name="monthly", quota_cycle="monthly"
            )
            _expired, _password, _token = await create_user(
                session, store, name="expired", expires_at=utcnow() - timedelta(days=1)
            )
            over, _password, _token = await create_user(session, store, name="over", quota_bytes=10)
            disabled, _password, _token = await create_user(session, store, name="disabled")
            disabled.enabled = False
            monthly.used_bytes = 100
            monthly.cycle_started_at = utcnow() - timedelta(days=40)
            over.used_bytes = 10
            await session.commit()

        calls: list[list[str]] = []

        async def on_quota(names: list[str]) -> None:
            calls.append(names)

        collector = StatsCollector(
            settings=settings, session_factory=factory, bus=EventBus(), on_quota=on_quota
        )
        await collector.enforce_quotas()
        async with factory() as session:
            rows = {row.name: row for row in (await session.execute(select(ProxyUser))).scalars()}
            assert rows["monthly"].used_bytes == 0
            assert rows["monthly"].enabled is True
            assert rows["expired"].disabled_reason == "expired"
            assert rows["over"].disabled_reason == "quota_exceeded"
            assert rows["disabled"].enabled is False
        assert calls and set(calls[0]) == {"expired", "over"}

        async def fail(names: list[str]) -> None:
            raise RuntimeError("apply failed")

        failing = StatsCollector(
            settings=settings, session_factory=factory, bus=EventBus(), on_quota=fail
        )
        await failing.enforce_quotas()  # no users to disable now; callback not invoked

        async def fail_enabled(names: list[str]) -> None:
            raise RuntimeError("apply failed")

        another = await _create_over(factory, store)
        failing.on_quota = fail_enabled
        await failing.enforce_quotas()
        assert another
        await engine.dispose()

    asyncio.run(_run())


async def _create_over(factory, store) -> bool:
    async with factory() as session:
        user, _password, _token = await create_user(session, store, name="over2", quota_bytes=1)
        user.used_bytes = 2
        await session.commit()
    return True


def test_snapshot_empty_and_disable_without_callback(tmp_path: Path) -> None:
    async def _run() -> None:
        settings, engine, factory, _store = await _setup(tmp_path)
        collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
        assert collector.snapshot() == {
            "online": 0,
            "rate_up": 0,
            "rate_down": 0,
            "users": [],
            "last_error": None,
        }
        await collector._disable(["nobody"])
        await collector.stop()
        await engine.dispose()

    asyncio.run(_run())


def test_usage_series_filter_epoch_and_speed_sample(tmp_path: Path) -> None:
    async def _run() -> None:
        _settings_value, engine, factory, store = await _setup(tmp_path)
        async with factory() as session:
            first, _password, _token = await create_user(session, store, name="first")
            second, _password, _token = await create_user(session, store, name="second")
            await session.commit()
            today = utcnow().date()
            yesterday = today - timedelta(days=1)
            session.add_all(
                [
                    TrafficDaily(user_id=first.id, day=today, uplink=1, downlink=2),
                    TrafficDaily(user_id=first.id, day=yesterday, uplink=3, downlink=4),
                    TrafficDaily(user_id=second.id, day=today, uplink=10, downlink=20),
                ]
            )
            await session.commit()

            everything = await usage_series(session, days=2)
            assert everything == [
                {"day": yesterday.isoformat(), "up": 3, "down": 4},
                {"day": today.isoformat(), "up": 11, "down": 22},
            ]
            only_first = await usage_series(session, days=2, user_id=first.id)
            assert only_first == [
                {"day": yesterday.isoformat(), "up": 3, "down": 4},
                {"day": today.isoformat(), "up": 1, "down": 2},
            ]
            await record_epoch(session, first.id, 2)
            await session.commit()

        assert SpeedSample().samples == []
        await engine.dispose()

    asyncio.run(_run())
