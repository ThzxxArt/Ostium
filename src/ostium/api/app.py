"""FastAPI application factory for the Ostium control plane."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from ostium import __version__
from ostium.api.deps import Services, client_ip, ensure_cli_token
from ostium.api.errors import ApiError, problem_response
from ostium.config import Role, Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.engine.manager import EngineManager
from ostium.engine.singbox.clash_api import ClashApi
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.jobs import JobManager, recover_jobs
from ostium.services.stats import StatsCollector
from ostium.services.users import ensure_inbounds

CSRF_COOKIE = "ostium_csrf"
# Hard ceiling for JSON API requests.  It must be enforced while streaming:
# reading an unbounded chunked body first would let an unauthenticated client
# exhaust control-plane memory before CSRF/authentication runs.
MAX_API_BODY_BYTES = 20 * 1024 * 1024
logger = logging.getLogger(__name__)


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """Read a request body without ever buffering more than ``limit`` bytes."""

    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if declared < 0:
            raise ValueError("invalid Content-Length")
        if declared > limit:
            raise BodyTooLarge
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise BodyTooLarge
    data = bytes(body)
    # Starlette caches ``_body``; populate it so downstream parsers do not try
    # to consume the already-drained receive channel.
    request._body = data
    return data


class BodyTooLarge(Exception):
    """The request body exceeded the configured streaming limit."""


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from ostium.config import InsecureBindError
        from ostium.services.backup import apply_pending_restore

        try:
            settings.validate_bind()
        except InsecureBindError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            apply_pending_restore(settings)
        except Exception as exc:
            logger.warning("staged backup restore failed and was kept for retry: %s", exc)
        engine = create_engine(settings.paths.db_path, echo=False)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        bus = EventBus()
        await recover_jobs(factory)
        jobs = JobManager(factory, bus)
        engine_manager = EngineManager(settings, factory, store, bus)

        async def on_quota(names: list[str]) -> None:
            async with factory() as session:
                try:
                    await engine_manager.apply_server(session)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    bus.log("error", "quota configuration apply failed", error=str(exc))

        stats = (
            StatsCollector(settings=settings, session_factory=factory, bus=bus, on_quota=on_quota)
            if settings.role is Role.SERVER
            else None
        )
        engine_manager.stats = stats
        clash = ClashApi(settings.paths.clash_secret_path)
        services = Services(
            settings=settings,
            session_factory=factory,
            store=store,
            bus=bus,
            jobs=jobs,
            engine=engine_manager,
            stats=stats,
            clash=clash,
        )
        app.state.services = services
        app.state.db_engine = engine
        ensure_cli_token(settings)
        if settings.role is Role.SERVER:
            async with factory() as session:
                with contextlib.suppress(Exception):
                    await ensure_inbounds(session, store)
                    await session.commit()
        elif settings.auto_connect:
            try:
                async with factory() as session:
                    await engine_manager.apply_client(
                        session, mode=settings.mode.value, tun_enabled=settings.tun_enabled
                    )
                bus.log("info", "auto-connect applied the active client profile")
            except Exception as exc:
                bus.log("warning", "auto-connect skipped", error=str(exc))
        with contextlib.suppress(Exception):
            await asyncio.to_thread(services.proxy.recover_if_stale)
        if stats is not None:
            await stats.start()
        services.tasks = [
            asyncio.create_task(_housekeeping(services), name="ostium-housekeeping"),
        ]
        if settings.role is Role.SERVER:
            services.tasks.append(
                asyncio.create_task(_cert_renewal(services), name="ostium-acme-renew")
            )
        else:
            services.tasks.append(
                asyncio.create_task(_profile_refresh(services), name="ostium-profile-refresh")
            )
            # Always run the watchdog; the switch is read every tick so toggling
            # auto-reconnect in Settings takes effect without a restart.
            services.tasks.append(
                asyncio.create_task(_core_watchdog(services), name="ostium-core-watchdog")
            )
        bus.log(
            "info", "Ostium control plane started", version=__version__, role=settings.role.value
        )
        try:
            yield
        finally:
            for task in services.tasks:
                task.cancel()
            for task in services.tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if stats is not None:
                await stats.stop()
            await jobs.shutdown()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(services.proxy.disable)
            await engine.dispose()

    app = FastAPI(
        title="Ostium API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = secrets.token_hex(8)
        request.state.csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        host = request.headers.get("host", "")
        if not _host_allowed(host, settings):
            return JSONResponse(
                status_code=400,
                content={"detail": "invalid Host header", "code": "invalid_host"},
            )
        origin = request.headers.get("origin")
        if origin and not _origin_allowed(origin, host):
            return JSONResponse(
                status_code=403,
                content={"detail": "cross-origin request rejected", "code": "origin_rejected"},
            )
        if request.url.path in {"/api/docs", "/api/openapi.json"}:
            authorized = await _docs_authorized(request)
            if not authorized:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "authentication required", "code": "unauthorized"},
                )
        if (
            settings.ui_allowlist
            and request.url.path not in {"/healthz", "/readyz"}
            and not request.url.path.startswith("/sub/")
        ):
            if not _ip_allowed(client_ip(request), settings.ui_allowlist):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "client address is not allowlisted", "code": "ip_denied"},
                )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
            "/api/"
        ):
            try:
                await _read_body_limited(request, MAX_API_BODY_BYTES)
            except BodyTooLarge:
                return JSONResponse(status_code=413, content={"detail": "body too large"})
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "invalid Content-Length", "code": "invalid_request"},
                )
            if request.url.path not in {
                "/api/v1/auth/login",
            } and not request.headers.get("authorization"):
                cookie = request.cookies.get(CSRF_COOKIE)
                header = request.headers.get("x-csrf-token")
                if not cookie or not header or not secrets.compare_digest(cookie, header):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "CSRF token missing or invalid",
                            "code": "csrf_failed",
                        },
                    )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; font-src 'self'; "
            "connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'"
        )
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(
                CSRF_COOKIE,
                request.state.csrf_token,
                httponly=False,
                samesite="strict",
                secure=settings.secure_cookies,
                path="/",
            )
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request,
            ApiError(
                422, "request validation failed", "validation_error", extra={"errors": exc.errors()}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/api/"):
            return problem_response(
                request, ApiError(exc.status_code, str(exc.detail), "http_error")
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled API error",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "path": request.url.path,
            },
        )
        return problem_response(request, ApiError(500, "internal server error", "internal_error"))

    from ostium.api import routes_auth

    app.include_router(routes_auth.router, prefix="/api/v1")
    _register_extra_routers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        services: Services = request.app.state.services
        checks: dict[str, bool] = {}
        try:
            async with services.session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            checks["database"] = False
        try:
            status = await services.engine.client.status()
            checks["core"] = bool(status.get("running"))
        except Exception:
            checks["core"] = False
        ready = checks["database"]
        return JSONResponse(
            status_code=200 if ready else 503, content={"ready": ready, "checks": checks}
        )

    dist = settings.paths.web_dist
    if dist is not None:
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        icons = dist / "icons"
        if icons.is_dir():
            app.mount("/icons", StaticFiles(directory=icons), name="icons")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith("api/") or path in {"healthz", "readyz", "metrics"}:
                return JSONResponse(status_code=404, content={"detail": "not found"})
            candidate = (dist / path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                return JSONResponse(status_code=404, content={"detail": "not found"})
            if path and candidate.is_file():
                return FileResponse(candidate)
            index = dist / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse(status_code=503, content={"detail": "frontend is not built"})
    else:

        @app.get("/", include_in_schema=False)
        async def no_frontend() -> PlainTextResponse:
            return PlainTextResponse(
                "Ostium API is running. Build the SPA with `npm --prefix web run build`.",
                status_code=200,
            )

    return app


async def _docs_authorized(request: Request) -> bool:
    """The OpenAPI UI and schema are admin-only, never anonymous."""

    services = getattr(request.app.state, "services", None)
    if services is None:
        return False
    from ostium.services.auth import get_admin, resolve_api_token, resolve_session

    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if _is_loopback_request(request):
            expected = services.cli_token()
            if expected and secrets.compare_digest(token, expected):
                async with services.session_factory() as session:
                    return await get_admin(session) is not None
        async with services.session_factory() as session:
            return await resolve_api_token(session, token) is not None
    cookie = request.cookies.get("ostium_session")
    if not cookie:
        return False
    async with services.session_factory() as session:
        return await resolve_session(session, cookie) is not None


def _is_loopback_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _ip_allowed(raw: str, networks: list[str]) -> bool:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    for entry in networks:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            # An invalid entry must never widen access.
            continue
    return False


def _host_allowed(host_header: str, settings: Settings) -> bool:
    host = host_header
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    host = host.strip().lower()
    if not host:
        return False
    allowed = {item.lower() for item in settings.trusted_hosts}
    allowed.update({"localhost", "127.0.0.1", "::1", "testserver"})
    if host in allowed:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        # Accept loopback/private interface literals (LAN access, containers)
        # but never an arbitrary public IP: that is a DNS-rebinding pivot.
        return address.is_loopback or address.is_private or address.is_link_local
    return any(host == item or host.endswith("." + item) for item in allowed if item != "*")


def _origin_allowed(origin: str, host_header: str) -> bool:
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if not parsed.netloc:
        return False
    return parsed.netloc.lower() == host_header.lower()


async def _housekeeping(
    services: Services, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    while True:
        try:
            await _run_housekeeping(services)
        except Exception as exc:
            services.bus.log("error", "housekeeping failed", error=str(exc))
        try:
            await sleep(3600)
        except asyncio.CancelledError:
            return


async def _run_housekeeping(services: Services) -> None:
    from datetime import timedelta

    from sqlalchemy import delete, select

    from ostium.db.models import (
        AuditLog,
        Backup,
        Certificate,
        Job,
        Session,
        TrafficDaily,
    )
    from ostium.services.audit import create_alert
    from ostium.services.backup import create_backup, prune_automatic_backups
    from ostium.services.settings import get_setting
    from ostium.util.time import as_utc, utcnow

    now = utcnow()
    async with services.session_factory() as session:
        audit_days = int(await get_setting(session, "audit_retention_days", 90) or 90)
        traffic_days = int(await get_setting(session, "traffic_retention_days", 365) or 365)
        job_days = int(await get_setting(session, "job_retention_days", 7) or 7)
        auto_backup = bool(await get_setting(session, "auto_backup", False))
        for row in (
            (await session.execute(select(Session).where(Session.expires_at < now))).scalars().all()
        ):
            await session.delete(row)
        for job in (
            (
                await session.execute(
                    select(Job).where(Job.created_at < now - timedelta(days=job_days))
                )
            )
            .scalars()
            .all()
        ):
            if job.status in {"succeeded", "failed", "cancelled", "interrupted"}:
                await session.delete(job)
        for entry in (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.created_at < now - timedelta(days=audit_days))
                )
            )
            .scalars()
            .all()
        ):
            await session.delete(entry)
        for traffic_row in (
            (
                await session.execute(
                    select(TrafficDaily).where(
                        TrafficDaily.day < (now - timedelta(days=traffic_days)).date()
                    )
                )
            )
            .scalars()
            .all()
        ):
            await session.delete(traffic_row)
        certs = (await session.execute(select(Certificate))).scalars().all()
        for cert in certs:
            if cert.expires_at is not None:
                days = (as_utc(cert.expires_at) - now).days
                if days < 14:
                    await create_alert(
                        session,
                        services.bus,
                        level="warning" if days >= 0 else "critical",
                        code="certificate_expiring",
                        message=f"certificate for {cert.domain} expires in {days} days",
                        dedupe_key=cert.domain,
                    )
        await session.commit()
    try:
        import psutil

        disk = psutil.disk_usage(str(services.settings.data_dir))
        if disk.percent >= 90:
            async with services.session_factory() as session:
                await create_alert(
                    session,
                    services.bus,
                    level="critical",
                    code="disk_low",
                    message=f"data disk is {disk.percent:.0f}% full",
                    dedupe_key="data",
                )
                await session.commit()
    except Exception:
        pass
    if auto_backup:
        try:
            newest = max(
                (
                    path.stat().st_mtime
                    for path in services.settings.paths.backups_dir.glob("ostium-auto-backup-*")
                ),
                default=0.0,
            )
            if now.timestamp() - newest >= 24 * 3600:
                result = await asyncio.to_thread(
                    create_backup, services.settings, automatic=True, include_master_key=True
                )
                services.bus.log("info", "automatic backup created", filename=result["filename"])
                async with services.session_factory() as backup_session:
                    backup_session.add(
                        Backup(
                            filename=result["filename"],
                            size=result["size"],
                            sha256=result["sha256"],
                            encrypted=result["encrypted"],
                        )
                    )
                    await backup_session.commit()
                removed = prune_automatic_backups(services.settings, keep=7)
                if removed:
                    async with services.session_factory() as prune_session:
                        await prune_session.execute(
                            delete(Backup).where(Backup.filename.in_(removed))
                        )
                        await prune_session.commit()
        except Exception as exc:
            services.bus.log("error", "automatic backup failed", error=str(exc))


async def _cert_renewal(
    services: Services, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    from sqlalchemy import select

    from ostium.acme.client import AcmeIssuer
    from ostium.db.models import Certificate
    from ostium.services.certificates import import_manual
    from ostium.util.time import as_utc, utcnow

    while True:
        try:
            await sleep(6 * 3600)
            async with services.session_factory() as session:
                certs = (await session.execute(select(Certificate))).scalars().all()
                for cert in certs:
                    if not cert.auto_renew or cert.source != "acme" or cert.expires_at is None:
                        continue
                    if (as_utc(cert.expires_at) - utcnow()).days >= 30:
                        continue
                    issuer = AcmeIssuer(services.settings, services.store)
                    fullchain, key_pem = await issuer.issue(cert.domain)
                    await import_manual(
                        session,
                        services.settings,
                        domain=cert.domain,
                        cert_pem=fullchain,
                        key_pem=key_pem,
                        source="acme",
                    )
                    await session.commit()
                    services.bus.log("info", "certificate renewed", domain=cert.domain)
                    try:
                        await services.engine.apply_server(session)
                    except Exception as exc:
                        services.bus.log(
                            "error", "apply after certificate renewal failed", error=str(exc)
                        )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            services.bus.log("error", "certificate renewal loop failed", error=str(exc))


async def _profile_refresh(
    services: Services, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    from sqlalchemy import select

    from ostium.db.models import Profile
    from ostium.services.profiles import refresh_profile

    while True:
        try:
            await sleep(24 * 3600)
            async with services.session_factory() as session:
                profiles = (
                    (
                        await session.execute(
                            select(Profile).where(
                                Profile.enabled.is_(True), Profile.subscription_url_enc.is_not(None)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for profile in profiles:
                    try:
                        await refresh_profile(session, services.store, profile)
                        services.bus.log("info", "subscription refreshed", profile=profile.name)
                    except Exception as exc:
                        services.bus.log(
                            "warning",
                            "subscription refresh failed",
                            profile=profile.name,
                            error=str(exc),
                        )
                await session.commit()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            services.bus.log("error", "profile refresh loop failed", error=str(exc))


async def _watchdog_tick(services: Services) -> None:
    """Restart a client core that disappeared after it had a good config."""

    if not services.settings.auto_reconnect or services.watchdog_suspended:
        return
    if not services.settings.paths.last_good_path.is_file():
        return
    try:
        status = await services.engine.client.status()
        if status.get("running"):
            return
    except Exception:
        pass
    try:
        await services.engine.client.reload()
        services.bus.log("info", "client core auto-reconnected")
    except Exception as exc:
        services.bus.log("warning", "client core auto-reconnect failed", error=str(exc))


async def _core_watchdog(
    services: Services, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    while True:
        try:
            await sleep(15)
            await _watchdog_tick(services)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            services.bus.log("error", "core watchdog failed", error=str(exc))


def _register_extra_routers(app: FastAPI) -> None:
    from ostium.api import (
        routes_alerts,
        routes_audit,
        routes_backups,
        routes_certs,
        routes_events,
        routes_inbounds,
        routes_jobs,
        routes_logs,
        routes_profiles,
        routes_rules,
        routes_settings,
        routes_stats,
        routes_subscriptions,
        routes_system,
        routes_users,
    )

    for module in (
        routes_inbounds,
        routes_users,
        routes_profiles,
        routes_rules,
        routes_settings,
        routes_stats,
        routes_logs,
        routes_certs,
        routes_jobs,
        routes_backups,
        routes_alerts,
        routes_audit,
        routes_system,
        routes_events,
    ):
        app.include_router(module.router, prefix="/api/v1")
    app.include_router(routes_subscriptions.router)


def create_app() -> FastAPI:
    return build_app()
