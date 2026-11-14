"""The minimal privileged core API (127.0.0.1:8788).

This app deliberately has no database, no static files and no shell access.  It
accepts only authenticated, role-compatible, whitelisted sing-box configurations
and supervises exactly one child process.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from ostium import __version__
from ostium.config import Role, Settings
from ostium.engine.singbox.supervisor import (
    CoreError,
    CoreSupervisor,
    ensure_core_token,
)
from ostium.engine.singbox.validate import ConfigRejected
from ostium.util.redact import redact

MAX_BODY_BYTES = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


class _BodyTooLarge(Exception):
    pass


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """Stream a request body without buffering more than ``limit`` bytes."""

    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if declared < 0:
            raise ValueError("invalid Content-Length")
        if declared > limit:
            raise _BodyTooLarge
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise _BodyTooLarge
    data = bytes(body)
    request._body = data
    return data


class ApplyRequest(BaseModel):
    config: dict[str, Any]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Role
    allow_lan: bool = False


def create_core_app(settings: Settings) -> FastAPI:
    supervisor = CoreSupervisor(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        ensure_core_token(settings.core_token_file)
        await supervisor.start()
        try:
            yield
        finally:
            await supervisor.shutdown()

    app = FastAPI(
        title="Ostium Core API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.supervisor = supervisor
    app.state.settings = settings

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                body = await _read_body_limited(request, MAX_BODY_BYTES)
            except _BodyTooLarge:
                return _problem(413, "request body too large", "body_too_large")
            except ValueError:
                return _problem(400, "invalid Content-Length", "invalid_request")
            content_type = request.headers.get("content-type", "")
            if body and not content_type.startswith("application/json"):
                return _problem(
                    415, "content type must be application/json", "unsupported_media_type"
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = ensure_core_token(settings.core_token_file)
        if not authorization or not authorization.startswith("Bearer "):
            raise _AuthError()
        provided = authorization[7:]
        if not secrets.compare_digest(provided, expected):
            raise _AuthError()

    @app.exception_handler(_AuthError)
    async def _auth_handler(_: Request, __: _AuthError) -> JSONResponse:
        return _problem(401, "missing or invalid core token", "unauthorized")

    @app.exception_handler(CoreError)
    async def _core_handler(_: Request, exc: CoreError) -> JSONResponse:
        return _problem(exc.status_code, redact(str(exc)), exc.code)

    @app.exception_handler(ConfigRejected)
    async def _config_handler(_: Request, exc: ConfigRejected) -> JSONResponse:
        return _problem(422, redact(str(exc)), exc.code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled core error", extra={"path": request.url.path})
        return _problem(500, "internal core error", "internal_error")

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        status = supervisor.status()
        return {"status": "ok", "running": status.running, "version": __version__}

    @app.get("/v1/status", dependencies=[Depends(require_token)])
    async def status() -> dict[str, Any]:
        return _status_payload(supervisor.status(), settings)

    @app.post("/v1/apply", dependencies=[Depends(require_token)])
    async def apply(request: ApplyRequest) -> dict[str, Any]:
        if request.role is not settings.role:
            raise ConfigRejected(
                "configuration role does not match this core service", "role_mismatch"
            )
        current = settings
        if settings.config_file.is_file():
            try:
                current = Settings.load(config_file=settings.config_file)
            except Exception:
                current = settings
        result = await supervisor.apply(
            request.config,
            request.sha256,
            allow_lan=request.allow_lan,
            allowed_ports=set(current.proxy_ports),
        )
        return _status_payload(result, settings)

    @app.post("/v1/reload", dependencies=[Depends(require_token)])
    async def reload() -> dict[str, Any]:
        return _status_payload(await supervisor.reload(), settings)

    @app.post("/v1/stop", dependencies=[Depends(require_token)])
    async def stop() -> dict[str, Any]:
        return _status_payload(await supervisor.stop_process(), settings)

    @app.get("/v1/logs", dependencies=[Depends(require_token)])
    async def logs(tail: int = Query(default=500, ge=1, le=5000)) -> PlainTextResponse:
        return PlainTextResponse(supervisor.read_logs(tail), media_type="text/plain; charset=utf-8")

    @app.get("/v1/config", dependencies=[Depends(require_token)])
    async def last_good() -> JSONResponse:
        path = settings.paths.last_good_path
        if not path.is_file():
            return _problem(404, "no configuration has been applied", "not_found")
        return JSONResponse(json.loads(path.read_bytes()))

    return app


class _AuthError(Exception):
    pass


def _status_payload(status: Any, settings: Settings) -> dict[str, Any]:
    return {
        "running": status.running,
        "pid": status.pid,
        "revision": status.revision,
        "config_sha256": status.config_sha256,
        "started_at": status.started_at,
        "updated_at": status.updated_at,
        "last_error": status.last_error,
        "engine_version": status.engine_version,
        "engine_path": status.engine_path,
        "role": settings.role.value,
        "core_version": __version__,
        "pid_file": str(settings.paths.core_state_path),
    }


def _problem(status: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": "Ostium core error",
            "status": status,
            "detail": detail,
            "code": code,
        },
        media_type="application/problem+json",
    )


def run_core(settings: Settings) -> None:
    import uvicorn

    port = int(settings.core_url.rsplit(":", 1)[-1]) if settings.core_url else 8788
    token = ensure_core_token(settings.core_token_file)
    if os.name == "posix":
        try:
            settings.core_token_file.chmod(0o600)
        except OSError:
            pass
    app = create_core_app(settings)
    if settings.role is Role.CLIENT and os.name == "posix":
        try:
            import grp

            group = grp.getgrnam("ostium")
            for path in (settings.data_dir, settings.paths.runtime_dir):
                os.chown(path, -1, group.gr_gid)
                path.chmod(0o750)
            os.chown(settings.core_token_file, -1, group.gr_gid)
            settings.core_token_file.chmod(0o640)
        except (KeyError, OSError):
            pass
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=settings.log_level,
        access_log=False,
        server_header=False,
        proxy_headers=False,
    )
    del token
