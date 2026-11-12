"""In-process event bus, live log buffer and WebSocket fan-out."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from ostium.util.redact import redact
from ostium.util.time import iso, utcnow


class EventBus:
    def __init__(self, log_capacity: int = 10_000) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._logs: deque[dict[str, Any]] = deque(maxlen=log_capacity)
        self._lock = asyncio.Lock()

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {"type": event_type, "ts": iso(utcnow()), "data": payload}
        async with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def log(self, level: str, message: str, **context: Any) -> None:
        record = {
            "ts": iso(utcnow()),
            "level": level.lower(),
            "message": redact(message),
            "context": {key: redact(str(value)) for key, value in context.items()},
        }
        self._logs.append(record)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish("log", record))

    def logs(
        self, *, level: str | None = None, search: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        items = list(self._logs)
        if level:
            items = [item for item in items if item["level"] == level]
        if search:
            needle = search.lower()
            items = [item for item in items if needle in item["message"].lower()]
        return items[-limit:]

    def export_logs(self) -> str:
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in self._logs)
