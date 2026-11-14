"""WebSocket event stream."""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ostium import __version__
from ostium.api.deps import Services, client_ip
from ostium.services.auth import resolve_session
from ostium.util.time import iso, utcnow

router = APIRouter()

PING_INTERVAL_SECONDS = 25
AUTH_REVALIDATE_SECONDS = 50


def _ip_allowed(raw: str, networks: list[str]) -> bool:
    import ipaddress

    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    for entry in networks:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _origin_matches(origin: str, host: str) -> bool:
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return bool(parsed.netloc) and parsed.netloc.lower() == host.lower()


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    services: Services = websocket.app.state.services
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host", "")
    # Browsers send Origin on WebSocket handshakes.  Reject cross-origin
    # consoles instead of relying on SameSite cookies alone.
    if origin and not _origin_matches(origin, host):
        await websocket.close(code=4403, reason="origin rejected")
        return
    if services.settings.ui_allowlist and not _ip_allowed(
        client_ip(websocket),
        services.settings.ui_allowlist,
    ):
        await websocket.close(code=4403, reason="client address is not allowlisted")
        return
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
    last_auth_check = asyncio.get_running_loop().time()
    try:
        await websocket.send_json(
            {"type": "hello", "ts": iso(utcnow()), "data": {"version": __version__}}
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_SECONDS)
            except TimeoutError:
                event = None
            # Revalidate on a time basis, not only after an idle timeout: a
            # busy event stream keeps resetting wait_for(), which previously
            # let revoked sessions receive events indefinitely.
            if asyncio.get_running_loop().time() - last_auth_check >= AUTH_REVALIDATE_SECONDS:
                async with services.session_factory() as session:
                    resolved = await resolve_session(session, token)
                    await session.commit()
                if resolved is None:
                    await websocket.close(code=4401, reason="session revoked")
                    return
                last_auth_check = asyncio.get_running_loop().time()
            if event is not None:
                await websocket.send_json(event)
            else:
                await websocket.send_json({"type": "ping", "ts": iso(utcnow()), "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        await services.bus.unsubscribe(queue)
