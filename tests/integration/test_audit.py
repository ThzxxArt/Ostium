from __future__ import annotations

import asyncio

import httpx
import respx

from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.audit import acknowledge, create_alert, list_alerts, send_webhook
from ostium.services.events import EventBus
from ostium.services.settings import set_setting


def test_alert_webhook_and_ack(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        bus = EventBus()
        async with factory() as session:
            await set_setting(session, "webhook_url", "https://example.com/hook")
            await set_setting(session, "webhook_secret", "secret")
            with respx.mock:
                route = respx.post("https://example.com/hook").mock(
                    return_value=httpx.Response(200)
                )
                alert = await create_alert(
                    session, bus, level="warning", code="test", message="hello"
                )
                await session.commit()
                await asyncio.sleep(0.05)
                assert route.called
                assert route.calls[0].request.headers["X-Ostium-Signature"]
            alerts = await list_alerts(session)
            assert len(alerts) == 1
            assert await acknowledge(session, alert.id)
            await session.commit()
            assert await list_alerts(session) == []
        await engine.dispose()

    asyncio.run(_run())


def test_webhook_requires_200() -> None:
    async def _run() -> None:
        with respx.mock:
            respx.post("https://example.com/fail").mock(return_value=httpx.Response(500))
            assert not await send_webhook("https://example.com/fail", {"x": 1})

    asyncio.run(_run())
