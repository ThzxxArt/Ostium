"""FastAPI dependencies and the shared service container."""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from fastapi import Depends, Request, WebSocket
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
    # Set by an explicit Disconnect so the auto-reconnect watchdog does not
    # immediately undo the operator's action.
    watchdog_suspended: bool = False
    # Persisted form of the same intent.  A control-plane or machine restart
    # must not resurrect last-good after the operator explicitly disconnected.
    client_paused: bool = False
    # Constructed on first use and cached.  ``system_proxy()`` probes the
    # desktop session with subprocess calls (gsettings/kreadconfig); callers
    # must evaluate this property inside ``asyncio.to_thread`` so a missing
    # session bus cannot stall the event loop.
    proxy_manager: Any = field(default=None, repr=False)
    # Runtime fail-open state, surfaced by /system/info so the UI can explain
    # why the system proxy is off while the core is down.
    proxy_fail_open_active: bool = False
    proxy_fail_open_since: str | None = None
    proxy_restore_pending: bool = False

    @property
    def proxy(self) -> Any:
        if self.proxy_manager is None:
            self.proxy_manager = system_proxy(self.settings)
        return self.proxy_manager

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


def client_ip(request: Request | WebSocket) -> str:
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
    # A request arriving through Nginx/Caddy has a loopback peer address, but
    # it is not a local operator.  Only direct loopback connections may use
    # the CLI token or one-time local-login links.
    if request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


_NARROW_WRITE_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("subscription:write", re.compile(r"^/api/v1/users/[^/]+/subscription/rotate$")),
)


def _narrow_write_scope_for(path: str, scopes: set[str]) -> str | None:
    """Return the narrow write scope that authorises this exact mutation.

    A token with ``subscription:write`` must not be able to POST ``/users``;
    the generic method gate only accepts the narrow scope on the route that
    the scope was designed for.  The endpoint's own ``require_scope`` still
    runs, so both checks must agree.
    """

    for scope, pattern in _NARROW_WRITE_ROUTES:
        if scope in scopes and pattern.match(path):
            return scope
    return None


async def get_current_admin(
    request: Request,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session, scope="function"),
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
            # Keep the scopes on the request so sensitive read endpoints can
            # require a narrower scope than the legacy blanket "read".
            request.state.api_token_scopes = scopes
            if not scopes.intersection({"read", "write"}):
                raise ApiError(403, "API token has no usable scope", "insufficient_scope")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                narrowed = _narrow_write_scope_for(request.url.path, scopes)
                if "write" not in scopes and narrowed is None:
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


def require_scope(scope: str) -> Callable[[Request], Awaitable[None]]:
    """Require a narrow scope for sensitive reads.

    Cookie sessions and the loopback CLI token are not API tokens and keep
    full access; only bearer API tokens are constrained.
    """

    async def dependency(request: Request) -> None:
        from ostium.api.errors import ApiError

        scopes = getattr(request.state, "api_token_scopes", None)
        if scopes is None:
            return
        if "write" in scopes or scope in scopes:
            return
        raise ApiError(
            403,
            f"API token lacks the {scope} scope",
            "insufficient_scope",
        )

    return dependency


def ensure_scope(request: Request, scope: str) -> None:
    """Enforce a narrow scope from inside a handler with a conditional path."""

    from ostium.api.errors import ApiError

    scopes = getattr(request.state, "api_token_scopes", None)
    if scopes is None:
        return
    if "write" in scopes or scope in scopes:
        return
    raise ApiError(403, f"API token lacks the {scope} scope", "insufficient_scope")


def actor_name(admin: AdminUser) -> str:
    return admin.username
