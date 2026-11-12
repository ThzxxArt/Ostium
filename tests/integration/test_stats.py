from __future__ import annotations

import asyncio
from pathlib import Path

from ostium.config import Role, Settings
from ostium.db.models import ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user


def _settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    value = Settings(
        role=Role.SERVER,
        data_dir=data,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=data / "runtime" / "core.token",
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    return value


def test_stats_epoch_flush_and_quota(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            user, _password, _token = await create_user(
                session, store, name="alice", quota_bytes=1000
            )
            await session.commit()
            user_id = user.id

        disabled: list[str] = []

        async def on_quota(names: list[str]) -> None:
            disabled.extend(names)

        collector = StatsCollector(
            settings=settings,
            session_factory=factory,
            bus=EventBus(),
            on_quota=on_quota,
            interval=0.01,
        )
        values = {"calls": 0}

        async def fake_query() -> dict[str, tuple[int, int]]:
            values["calls"] += 1
            if values["calls"] == 1:
                return {"alice": (0, 0)}
            return {"alice": (800, 300)}

        collector.client.query_users = fake_query  # type: ignore[method-assign]
        await collector.tick()  # baseline
        await collector.tick()  # 1100 bytes delta
        await collector.flush()

        async with factory() as session:
            refreshed = await session.get(ProxyUser, user_id)
            assert refreshed is not None
            assert refreshed.used_bytes == 1100
            assert refreshed.last_seen_at is not None
        await collector.enforce_quotas()
        async with factory() as session:
            refreshed = await session.get(ProxyUser, user_id)
            assert refreshed is not None
            assert refreshed.enabled is False
            assert refreshed.disabled_reason == "quota_exceeded"

        assert disabled == ["alice"]
        snapshot = collector.snapshot()
        assert snapshot["online"] == 1
        await engine.dispose()

    asyncio.run(_run())


def test_stats_counter_reset_is_treated_as_new_epoch(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="bob")
            await session.commit()
            user_id = user.id
        collector = StatsCollector(
            settings=settings,
            session_factory=factory,
            bus=EventBus(),
            interval=0.01,
        )
        values = iter([(0, 0), (100, 50), (10, 5)])

        async def fake_query() -> dict[str, tuple[int, int]]:
            try:
                return {"bob": next(values)}
            except StopIteration:
                return {"bob": (10, 5)}

        collector.client.query_users = fake_query  # type: ignore[method-assign]
        await collector.tick()
        await collector.tick()
        await collector.tick()  # reset: add the new counter rather than a negative delta
        await collector.flush()
        async with factory() as session:
            refreshed = await session.get(ProxyUser, user_id)
            assert refreshed is not None
            assert refreshed.used_bytes == 165
        await engine.dispose()

    asyncio.run(_run())
