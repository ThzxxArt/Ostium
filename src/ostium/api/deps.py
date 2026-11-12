"""FastAPI dependencies and the shared service container."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ostium.config import Settings
from ostium.db.models import AdminUser
from ostium.engine.manager import EngineManager
from ostium.engine.singbox.clash_api import ClashApi
from ostium.services.auth import get_admin, resolve_api_token, resolve_session
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.jobs import JobManager
from ostium.services.stats import StatsCollector
from ostium.system.proxy import system_proxy
from ostium.util.security import constant_time_equal
from ostium.util.time import utcnow


@dataclass
class Services:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    store: SecretStore
    bus: EventBus
    jobs: JobManager
    engine: EngineManager
    stats: StatsCollector | None
    clash: ClashApi
    started_at: datetime = field(default_factory=utcnow)
    tasks: list[Any] = field(default_factory=list)

    @property
    def proxy(self) -> Any:
        return system_proxy(self.settings)

    def cli_token(self) -> str:
        return ensure_cli_token(self.settings)


def ensure_cli_token(settings: Settings) -> str:
    path = settings.paths.runtime_dir / "cli.token"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(48)
    path.write_text(token, encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    return token


def get_services(request: Request) -> Services:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise RuntimeError("application services are not initialized")
    return cast(Services, services)


async def get_session(services: Services = Depends(get_services)) -> AsyncIterator[AsyncSession]:
    session = services.session_factory()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and request.client and request.client.host in {"127.0.0.1", "::1"}:
        # Only the hop added by our own reverse proxy is trusted.  Taking the
        # last entry prevents a client from spoofing the first entry to bypass
        # login/subscription rate limits or poison audit logs.  The shipped
        # Nginx config also overwrites the header with $remote_addr.
        candidate = forwarded.rsplit(",", 1)[-1].strip()
        if candidate:
            return candidate
    return request.client.host if request.client else "unknown"


def is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


async def get_current_admin(
    request: Request,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> AdminUser:
    from ostium.api.errors import ApiError

    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if is_loopback(request):
            try:
                expected = services.cli_token()
            except OSError:
                expected = ""
            if expected and constant_time_equal(token, expected):
                admin = await get_admin(session)
                if admin is not None:
                    return admin
        api_token = await resolve_api_token(session, token)
        if api_token is not None:
            scopes = set(api_token.scopes or [])
            if not scopes.intersection({"read", "write"}):
                raise ApiError(403, "API token has no usable scope", "insufficient_scope")
            if request.method not in {"GET", "HEAD", "OPTIONS"} and "write" not in scopes:
                raise ApiError(403, "API token lacks the write scope", "insufficient_scope")
            admin = await get_admin(session)
            if admin is not None:
                return admin
        raise ApiError(401, "invalid or expired token", "unauthorized")
    cookie = request.cookies.get("ostium_session")
    if not cookie:
        raise ApiError(401, "authentication required", "unauthorized")
    resolved = await resolve_session(session, cookie)
    if resolved is None:
        raise ApiError(401, "session expired", "session_expired")
    admin, _row = resolved
    return admin


def actor_name(admin: AdminUser) -> str:
    return admin.username
