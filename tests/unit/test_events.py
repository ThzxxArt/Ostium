from __future__ import annotations

import asyncio

from ostium.services.events import EventBus


def test_event_bus_pubsub_and_logs() -> None:
    async def _run() -> None:
        bus = EventBus(log_capacity=10)
        queue = await bus.subscribe()
        await bus.publish("test.event", {"value": 1})
        frame = await asyncio.wait_for(queue.get(), timeout=1)
        assert frame["type"] == "test.event"
        assert frame["data"]["value"] == 1
        await bus.unsubscribe(queue)

        bus.log("info", "hello", user="alice")
        records = bus.logs(level="info")
        assert records[-1]["message"] == "hello"
        assert records[-1]["context"]["user"] == "alice"
        assert "hello" in bus.export_logs()

        bus.log(
            "error",
            "failed for 2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        )
        assert "2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e" not in bus.export_logs()
        assert "[REDACTED-UUID]" in bus.export_logs()

    asyncio.run(_run())
