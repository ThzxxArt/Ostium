"""System status, proxy/TUN switches, diagnostics and service control."""

from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import socket
import ssl
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, cast

import psutil
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium import __version__
from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.config import Mode, Role
from ostium.db.models import AdminUser, Certificate
from ostium.services.audit import audit
from ostium.services.users import server_hostname
from ostium.util.redact import redact
from ostium.util.time import as_utc, iso, utcnow

router = APIRouter(tags=["system"])


class ProxyToggle(BaseModel):
    enabled: bool


class TunToggle(BaseModel):
    enabled: bool


class ModeRequest(BaseModel):
    mode: str


@router.get("/system/info")
async def info(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(services.settings.data_dir))
    try:
        core = await asyncio.wait_for(services.engine.client.status(), timeout=2.5)
    except Exception as exc:
        core = {"running": False, "last_error": str(exc) or "core service is unreachable"}
    return {
        "app": {"name": "Ostium", "version": __version__, "role": services.settings.role.value},
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "uptime_seconds": int(time.time() - psutil.boot_time()),
            "pid": os.getpid(),
        },
        "metrics": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "load_1m": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
            "memory_percent": memory.percent,
            "memory_used": memory.used,
            "memory_total": memory.total,
            "disk_percent": disk.percent,
            "disk_used": disk.used,
            "disk_total": disk.total,
        },
        "core": core,
        "control_plane_uptime": int((utcnow() - services.started_at).total_seconds()),
        "server_host": await server_hostname(session)
        if services.settings.role is Role.SERVER
        else None,
        "mode": services.settings.mode.value,
        "proxy": services.proxy.status(),
        "tun": {
            "enabled": services.settings.tun_enabled,
            "interface": services.settings.tun_interface,
            "mtu": 1500,
            "stack": "gvisor",
        },
    }


@router.get("/system/doctor")
async def doctor(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, message: str, fix: str | None = None) -> None:
        checks.append({"id": name, "status": status, "message": message, "fix": fix})

    try:
        async with services.session_factory() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
        add("database", "pass", "SQLite database is readable")
    except Exception as exc:
        add("database", "fail", f"database check failed: {exc}", "check data directory permissions")
    try:
        core = await services.engine.client.status()
        if core.get("running"):
            add("core", "pass", f"sing-box is running (pid {core.get('pid')})")
        else:
            add(
                "core", "warn", "sing-box is not running", "open System and apply the configuration"
            )
    except Exception as exc:
        add("core", "fail", f"core API unreachable: {exc}", "start ostium-core.service")
    engine = services.settings.paths.engine_binary
    if engine.is_file():
        add("engine", "pass", f"core binary found at {engine}")
    else:
        add("engine", "fail", f"core binary missing at {engine}", "run `ostium core install`")
    proxy = services.proxy.status()
    proxy_message = (
        f"system proxy: {'enabled' if proxy.get('enabled') else 'disabled'} "
        f"({proxy.get('platform')})"
    )
    add(
        "system_proxy",
        "pass" if proxy.get("supported") else "warn",
        proxy_message,
    )
    if services.settings.role is Role.CLIENT:
        tun_ok = os.name == "nt" or os.geteuid() == 0 or Path("/dev/net/tun").exists()
        add(
            "tun",
            "pass" if tun_ok else "warn",
            "TUN device is available" if tun_ok else "/dev/net/tun is not available",
            None if tun_ok else "install/start ostium-core.service with CAP_NET_ADMIN",
        )
    certs = (await session.execute(select(Certificate))).scalars().all()
    for cert in certs:
        if cert.expires_at is not None:
            days = (as_utc(cert.expires_at) - utcnow()).days
            add(
                f"certificate:{cert.domain}",
                "pass" if days > 14 else ("warn" if days >= 0 else "fail"),
                f"certificate expires in {days} days",
                "renew the certificate" if days <= 14 else None,
            )
    return {"checks": checks, "generated_at": iso(utcnow())}


@router.post("/system/proxy")
async def toggle_proxy(
    payload: ProxyToggle,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "system proxy is a client feature", "role_mismatch")
    if services.settings.tun_enabled and payload.enabled:
        raise ApiError(409, "TUN and system proxy are mutually exclusive", "mode_conflict")
    if payload.enabled:
        try:
            result = services.proxy.enable("127.0.0.1", services.settings.mixed_port)
        except Exception as exc:
            raise ApiError(500, f"could not enable system proxy: {exc}", "proxy_failed") from exc
        services.settings.mode = Mode.SYSTEM_PROXY
    else:
        try:
            result = services.proxy.disable()
        except Exception as exc:
            raise ApiError(500, f"could not disable system proxy: {exc}", "proxy_failed") from exc
        if services.settings.mode is Mode.SYSTEM_PROXY:
            services.settings.mode = Mode.MIXED
    await audit(
        session,
        actor=admin.username,
        action="system.proxy_toggled",
        target=str(payload.enabled),
        ip=client_ip(request),
    )
    await services.bus.publish("system.proxy", result)
    return cast(dict[str, Any], result)


@router.post("/system/tun")
async def toggle_tun(
    payload: TunToggle,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "TUN is a client feature", "role_mismatch")
    if payload.enabled:
        if services.proxy.status().get("enabled"):
            try:
                services.proxy.disable()
            except Exception:
                pass
        services.settings.tun_enabled = True
        services.settings.mode = Mode.TUN
        try:
            result = await services.engine.apply_client(session, mode="tun", tun_enabled=True)
        except Exception as exc:
            services.settings.tun_enabled = False
            services.settings.mode = Mode.MIXED
            raise ApiError(500, f"TUN could not be enabled: {exc}", "tun_failed") from exc
        message = "TUN enabled"
    else:
        services.settings.tun_enabled = False
        services.settings.mode = Mode.MIXED
        try:
            result = await services.engine.apply_client(session, mode="mixed", tun_enabled=False)
        except Exception as exc:
            raise ApiError(500, f"TUN could not be disabled cleanly: {exc}", "tun_failed") from exc
        message = "TUN disabled and routes cleaned up"
    try:
        services.settings.save()
    except OSError:
        pass
    await audit(
        session,
        actor=admin.username,
        action="system.tun_toggled",
        target=str(payload.enabled),
        ip=client_ip(request),
    )
    return {"ok": True, "message": message, "status": result.get("status")}


@router.post("/system/mode")
async def set_mode(
    payload: ModeRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "connection modes are a client feature", "role_mismatch")
    try:
        mode = Mode(payload.mode)
    except ValueError as exc:
        raise ApiError(400, "mode must be mixed, system_proxy or tun", "bad_mode") from exc
    if mode is Mode.TUN:
        return await toggle_tun(TunToggle(enabled=True), request, admin, services, session)
    if services.settings.tun_enabled:
        await toggle_tun(TunToggle(enabled=False), request, admin, services, session)
    if mode is Mode.SYSTEM_PROXY:
        if not services.proxy.status().get("enabled"):
            await toggle_proxy(ProxyToggle(enabled=True), request, admin, services, session)
    elif services.proxy.status().get("enabled"):
        await toggle_proxy(ProxyToggle(enabled=False), request, admin, services, session)
    services.settings.mode = mode
    try:
        services.settings.save()
    except OSError:
        pass
    if mode is Mode.MIXED and services.settings.role is Role.CLIENT:
        try:
            await services.engine.apply_client(session, mode="mixed", tun_enabled=False)
        except Exception:
            pass
    return {"mode": mode.value}


@router.post("/system/connect")
async def connect(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "connect is a client action", "role_mismatch")
    try:
        result = await services.engine.apply_client(session)
    except Exception as exc:
        code = getattr(exc, "code", "engine_error")
        status = getattr(exc, "status_code", 502)
        raise ApiError(status, str(exc), code) from exc
    await audit(session, actor=admin.username, action="client.connect", ip=client_ip(request))
    return {"connected": True, "status": result.get("status")}


@router.post("/system/disconnect")
async def disconnect(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "disconnect is a client action", "role_mismatch")
    if services.proxy.status().get("enabled"):
        try:
            services.proxy.disable()
        except Exception:
            pass
    try:
        status = await services.engine.client.stop()
    except Exception as exc:
        raise ApiError(502, f"could not stop the core: {exc}", "core_error") from exc
    await audit(session, actor=admin.username, action="client.disconnect", ip=client_ip(request))
    return {"connected": False, "status": status}


@router.get("/system/services")
async def services_status(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        core = await services.engine.client.status()
        core_reachable = True
    except Exception as exc:
        core = {"running": False, "last_error": str(exc)}
        core_reachable = False
    return {
        "services": [
            {
                "name": "ostium.service",
                "label": "Control plane",
                "running": True,
                "detail": f"pid {os.getpid()}",
            },
            {
                "name": "ostium-core.service",
                "label": "Proxy core",
                "running": bool(core.get("running")),
                "reachable": core_reachable,
                "detail": core,
            },
        ]
    }


@router.post("/system/services/{name}/restart")
async def restart_service(
    name: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if name not in {"ostium", "ostium-core"}:
        raise ApiError(404, "unknown service", "not_found")
    if name == "ostium":
        raise ApiError(
            409,
            "the control plane cannot restart itself; run `sudo systemctl restart ostium`",
            "restart_required",
        )
    try:
        status = await services.engine.client.reload()
    except Exception as exc:
        raise ApiError(502, f"core reload failed: {exc}", "core_error") from exc
    await audit(session, actor=admin.username, action="system.core_reloaded", ip=client_ip(request))
    return {"restarted": True, "status": status}


@router.get("/system/diagnostics")
async def diagnostics(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    doctor_result = await doctor(_, services, session)
    try:
        core_cfg = await services.engine.client.config()
        core_cfg_text = redact(json.dumps(core_cfg, indent=2))
    except Exception as exc:
        core_cfg_text = f"unavailable: {exc}"
    return {
        "version": __version__,
        "role": services.settings.role.value,
        "generated_at": iso(utcnow()),
        "checks": doctor_result["checks"],
        "config": core_cfg_text,
        "logs": services.bus.logs(limit=200),
        "system": {
            "platform": platform.platform(),
            "python": sys.version,
            "hostname": socket.gethostname(),
        },
    }


@router.get("/system/diagnostics/download")
async def diagnostics_download(
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Response:
    payload = await diagnostics(admin, services, session)
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("ostium-diagnostics.json")
        info.size = len(body)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(body))
    return Response(
        content=buffer.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="ostium-diagnostics.tar.gz"'},
    )


@router.post("/system/preflight/reality")
async def preflight_reality(
    host: str = "www.apple.com",
    port: int = 443,
    _: AdminUser = Depends(get_current_admin),
) -> dict[str, Any]:
    try:
        context = ssl.create_default_context()
        with (
            socket.create_connection((host, port), timeout=8) as sock,
            context.wrap_socket(sock, server_hostname=host) as tls,
        ):
            version = tls.version()
            cipher = tls.cipher()
        ok = version == "TLSv1.3"
        return {
            "ok": ok,
            "host": host,
            "tls_version": version,
            "cipher": cipher[0] if cipher else None,
            "message": "TLS 1.3 handshake succeeded" if ok else "TLS 1.3 is required for Reality",
        }
    except Exception as exc:
        return {"ok": False, "host": host, "message": str(exc)}
