"""WebSocket event stream."""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ostium import __version__
from ostium.api.deps import Services
from ostium.services.auth import resolve_session
from ostium.util.time import iso, utcnow

router = APIRouter()


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    services: Services = websocket.app.state.services
    token = websocket.cookies.get("ostium_session")
    if not token:
        await websocket.close(code=4401, reason="authentication required")
        return
    async with services.session_factory() as session:
        resolved = await resolve_session(session, token)
        if resolved is None:
            await websocket.close(code=4401, reason="session expired")
            return
        await session.commit()
    await websocket.accept()
    queue = await services.bus.subscribe()
    try:
        await websocket.send_json(
            {"type": "hello", "ts": iso(utcnow()), "data": {"version": __version__}}
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(event)
            except TimeoutError:
                await websocket.send_json({"type": "ping", "ts": iso(utcnow()), "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        await services.bus.unsubscribe(queue)
