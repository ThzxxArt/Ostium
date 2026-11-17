"""System-proxy fail-open must be bounded and must respect Disconnect."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from ostium.api.app import _proxy_watchdog_tick, _ProxyWatchdogState
from ostium.config import Mode, Role, Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.events import EventBus


class FakeProxy:
    def __init__(self) -> None:
        self.enabled = True
        self.disable_calls = 0
        self.enable_calls = 0

    def status(self) -> dict[str, object]:
        return {"enabled": self.enabled, "supported": True, "platform": "test"}

    def disable(self) -> dict[str, object]:
        self.disable_calls += 1
        self.enabled = False
        return self.status()

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, object]:
        self.enable_calls += 1
        self.enabled = True
        return self.status()


class FakeEngine:
    def __init__(self) -> None:
        self.running = False
        self.client = SimpleNamespace(status=self._status)
        self.reconciled = 0

    async def _status(self) -> dict[str, object]:
        return {"running": self.running}

    async def reconcile_client(self, session: object, *, force: bool = False) -> None:
        self.reconciled += 1


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    data = tmp_path / "data"
    values: dict[str, object] = {
        "role": Role.CLIENT,
        "data_dir": data,
        "config_dir": tmp_path / "config",
        "state_dir": tmp_path / "state",
        "core_token_file": data / "runtime" / "core.token",
        "mode": Mode.SYSTEM_PROXY,
        "dev": True,
        "log_level": "warning",
        "system_proxy_fail_open": True,
        "system_proxy_fail_open_seconds": 45,
    }
    values.update(overrides)
    value = Settings(**values)  # type: ignore[arg-type]
    value.paths.ensure()
    return value


def test_fail_open_threshold_and_recovery(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        proxy = FakeProxy()
        engine_stub = FakeEngine()
        services = SimpleNamespace(
            settings=settings,
            session_factory=factory,
            bus=EventBus(),
            proxy=proxy,
            engine=engine_stub,
            client_paused=False,
            proxy_fail_open_active=False,
            proxy_fail_open_since=None,
            proxy_restore_pending=False,
        )
        state = _ProxyWatchdogState()

        await _proxy_watchdog_tick(services, state, 100.0)
        assert proxy.disable_calls == 0
        await _proxy_watchdog_tick(services, state, 144.9)
        assert proxy.disable_calls == 0
        await _proxy_watchdog_tick(services, state, 145.0)
        assert proxy.disable_calls == 1
        assert services.proxy_fail_open_active is True
        assert services.proxy_restore_pending is True
        assert engine_stub.reconciled == 1

        engine_stub.running = True
        await _proxy_watchdog_tick(services, state, 150.0)
        assert proxy.enable_calls == 1
        assert services.proxy_fail_open_active is False
        assert services.proxy_restore_pending is False
        await engine.dispose()

    asyncio.run(_run())


def test_explicit_disconnect_is_not_undone(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        proxy = FakeProxy()
        engine_stub = FakeEngine()
        services = SimpleNamespace(
            settings=settings,
            session_factory=factory,
            bus=EventBus(),
            proxy=proxy,
            engine=engine_stub,
            client_paused=True,
            proxy_fail_open_active=True,
            proxy_fail_open_since="2026-11-17T00:00:00+00:00",
            proxy_restore_pending=True,
        )
        state = _ProxyWatchdogState()
        await _proxy_watchdog_tick(services, state, 1000.0)
        assert proxy.disable_calls == 0
        assert proxy.enable_calls == 0
        assert services.proxy_restore_pending is False
        await engine.dispose()

    asyncio.run(_run())


def test_fail_open_disabled_keeps_the_proxy(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path, system_proxy_fail_open=False)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        proxy = FakeProxy()
        engine_stub = FakeEngine()
        services = SimpleNamespace(
            settings=settings,
            session_factory=factory,
            bus=EventBus(),
            proxy=proxy,
            engine=engine_stub,
            client_paused=False,
            proxy_fail_open_active=False,
            proxy_fail_open_since=None,
            proxy_restore_pending=False,
        )
        state = _ProxyWatchdogState()
        await _proxy_watchdog_tick(services, state, 10.0)
        await _proxy_watchdog_tick(services, state, 60.0)
        assert proxy.disable_calls == 0
        assert services.proxy_fail_open_active is False
        await engine.dispose()

    asyncio.run(_run())
