from __future__ import annotations

import asyncio
from pathlib import Path

from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.manager import EngineManager
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.profiles import create_profile
from ostium.services.users import create_user, ensure_inbounds


def test_server_and_client_preview(settings: Settings, tmp_path: Path) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        manager = EngineManager(settings, factory, store, EventBus())
        async with factory() as session:
            await ensure_inbounds(session, store)
            await create_user(session, store, name="alice")
            await session.commit()
            server = await manager.server_preview(session)
            assert server["inbounds"][0]["type"] == "vless"
            assert server["experimental"]["v2ray_api"]["stats"]["users"] == ["alice"]

            endpoint = Endpoint(
                tag="reality",
                protocol=Protocol.VLESS_REALITY,
                name="HK",
                server="127.0.0.1",
                port=443,
                uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                tls=TLSConfig(
                    reality_public_key="pub",
                    reality_short_id="sid",
                ),
            )
            profile = await create_profile(session, store, name="HK", endpoints=[endpoint])
            await session.commit()
            client = await manager.client_preview(session, mode="mixed")
            assert client["inbounds"][0]["type"] == "mixed"
            assert profile.id

            async def fake_apply(config, digest, role):  # type: ignore[no-untyped-def]
                return {"running": True, "revision": digest[:16], "role": role}

            manager.client.apply = fake_apply  # type: ignore[method-assign]
            result = await manager.apply_client(session)
            assert result["status"]["running"] is True
        await engine.dispose()

    asyncio.run(_run())
