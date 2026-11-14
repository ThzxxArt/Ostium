"""Public URL and subscription-host convergence (P0-04)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ostium.config import Role, Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.public_url import base_url_for_domain, public_base_url
from ostium.services.settings import set_setting
from ostium.services.users import server_hostname


def _settings(tmp_path: Path, *, public_ui: bool, port: int = 8443) -> Settings:
    value = Settings(
        role=Role.SERVER,
        public_ui=public_ui,
        port=port,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


async def _session(settings: Settings):
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    return engine, create_session_factory(engine)


def test_public_ui_default_port_is_in_subscription_base(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path, public_ui=True, port=8443)
        engine, factory = await _session(settings)
        async with factory() as session:
            await set_setting(session, "server", {"domain": "vpn.example.com"})
            await session.commit()
            assert await public_base_url(session, settings) == "https://vpn.example.com:8443"
        await engine.dispose()

    asyncio.run(_run())


def test_nginx_mode_uses_tls_on_443_without_backend_port(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path, public_ui=False, port=8443)
        engine, factory = await _session(settings)
        async with factory() as session:
            await set_setting(session, "server", {"domain": "vpn.example.com"})
            await session.commit()
            assert await public_base_url(session, settings) == "https://vpn.example.com"
        await engine.dispose()

    asyncio.run(_run())


def test_server_hostname_prefers_explicit_public_base_url(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path, public_ui=True)
        engine, factory = await _session(settings)
        async with factory() as session:
            await set_setting(session, "public_base_url", "https://edge.example.com:9443")
            await set_setting(session, "server", {"public_host": "old.example.com"})
            await session.commit()
            assert await server_hostname(session) == "edge.example.com"
        await engine.dispose()

    asyncio.run(_run())


def test_base_url_for_domain_preserves_absolute_values(tmp_path: Path) -> None:
    settings = _settings(tmp_path, public_ui=True)
    assert base_url_for_domain(settings, "vpn.example.com") == "https://vpn.example.com:8443"
    assert (
        base_url_for_domain(settings, "https://vpn.example.com/custom")
        == "https://vpn.example.com/custom"
    )
