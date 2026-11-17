"""System status, proxy/TUN switches, diagnostics and service control."""

from __future__ import annotations

import asyncio
import io
import ipaddress
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
from ostium.build_info import build_info, listener_info, read_web_build, version_mismatches
from ostium.config import Mode, Role
from ostium.db.models import AdminUser, Certificate
from ostium.services.audit import audit
from ostium.services.users import server_hostname
from ostium.util.redact import redact
from ostium.util.time import as_utc, iso, utcnow

router = APIRouter(tags=["system"])


def _lan_addresses() -> list[str]:
    """Return private, non-loopback IPv4 addresses for the LAN sharing hint."""

    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        # Some VPS/container network stacks do not expose every address family
        # through psutil (for example AF_PACKET may be unavailable).  LAN hints
        # are optional; they must not take down the dashboard.
        return []
    addresses: set[str] = set()
    for entries in interfaces.values():
        for entry in entries:
            if entry.family != socket.AF_INET:
                continue
            try:
                address = ipaddress.ip_address(entry.address)
            except ValueError:
                continue
            if address.is_loopback or address.is_link_local or not address.is_private:
                continue
            addresses.add(str(address))
    return sorted(addresses)


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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(services.settings.data_dir))
    build = build_info()
    try:
        core = await asyncio.wait_for(services.engine.client.status(), timeout=2.5)
    except Exception as exc:
        core = {"running": False, "last_error": str(exc) or "core service is unreachable"}
    return {
        "app": {
            "name": "Ostium",
            "version": __version__,
            "commit": build.commit,
            "built_at": build.built_at,
            "frozen": build.frozen,
            "role": services.settings.role.value,
        },
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
        "allow_lan": services.settings.allow_lan,
        "mixed_port": services.settings.mixed_port,
        "lan_addresses": _lan_addresses(),
        "lan_port": services.settings.mixed_port,
        "proxy": await asyncio.to_thread(lambda: services.proxy.status()),
        "tun": {
            "enabled": services.settings.tun_enabled,
            "interface": services.settings.tun_interface,
            "mtu": services.settings.tun_mtu,
            "stack": services.settings.tun_stack,
        },
    }


@router.get("/system/provenance")
async def provenance(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Report every observable version surface and the listening process.

    A 200 from ``/healthz`` is not proof that the expected release is running:
    an old process can still own the port.  This endpoint binds the answer to a
    PID, an executable path and the actual process start time.
    """

    build = build_info()
    web = read_web_build(services.settings.paths.web_dist)
    try:
        core = await asyncio.wait_for(services.engine.client.status(), timeout=2.0)
        core_reachable = True
    except Exception as exc:
        core = {"running": False, "last_error": str(exc) or "core service is unreachable"}
        core_reachable = False
    listener = await asyncio.to_thread(
        listener_info, services.settings.port, host=services.settings.host
    )
    listener["is_control_plane"] = listener.get("pid") == os.getpid()
    core_version = core.get("core_version") if isinstance(core, dict) else None
    web_version = web.get("version") if web.get("available") else None
    mismatches = version_mismatches(
        build.version,
        core=str(core_version) if core_version else None,
        web=str(web_version) if web_version else None,
    )
    return {
        "app": build.as_dict(),
        "web": web,
        "core": {
            "reachable": core_reachable,
            "running": bool(core.get("running")) if isinstance(core, dict) else False,
            "version": core_version,
            "pid": core.get("pid") if isinstance(core, dict) else None,
            "engine_version": core.get("engine_version") if isinstance(core, dict) else None,
            "revision": core.get("revision") if isinstance(core, dict) else None,
            "config_sha256": core.get("config_sha256") if isinstance(core, dict) else None,
            "last_error": core.get("last_error") if isinstance(core, dict) else None,
        },
        "listener": listener,
        "consistency": {
            "ok": not mismatches,
            "expected_version": build.version,
            "mismatches": mismatches,
        },
        "generated_at": iso(utcnow()),
    }


@router.get("/system/port-owners")
async def port_owners(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    ports = sorted(
        {
            int(services.settings.port),
            int(services.settings.mixed_port),
            int(services.settings.core_url.rsplit(":", 1)[-1])
            if services.settings.core_url.rsplit(":", 1)[-1].isdigit()
            else 8788,
        }
    )
    owners = await asyncio.to_thread(lambda: [listener_info(port) for port in ports])
    return {"owners": owners, "generated_at": iso(utcnow())}


@router.get("/system/doctor")
async def doctor(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(
        name: str,
        status: str,
        message: str,
        fix: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            {"id": name, "status": status, "message": message, "fix": fix, "data": data or {}}
        )

    build = build_info()
    add(
        "version",
        "pass" if build.version != "0.0.0" else "fail",
        f"control plane {build.version}"
        + (f" ({build.commit[:12]})" if build.commit else " (commit unknown)"),
        None if build.version != "0.0.0" else "reinstall from a release artifact",
        {
            "version": build.version,
            "commit": build.commit,
            "source": build.as_dict()["version_source"],
        },
    )
    listener = await asyncio.to_thread(
        listener_info, services.settings.port, host=services.settings.host
    )
    if not listener.get("found"):
        add(
            f"port_owner:{services.settings.port}",
            "fail",
            f"nothing is listening on {services.settings.host}:{services.settings.port}",
            "start the control plane and re-run doctor",
            listener,
        )
    elif listener.get("pid") == os.getpid():
        add(
            f"port_owner:{services.settings.port}",
            "pass",
            f"listener pid {listener.get('pid')} is this process ({listener.get('exe')})",
            None,
            listener,
        )
    else:
        add(
            f"port_owner:{services.settings.port}",
            "warn",
            f"port is owned by pid {listener.get('pid')} ({listener.get('exe')}), "
            "which is not this process",
            "stop the stale process or start the expected control plane",
            listener,
        )

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
        core = {}
        add("core", "fail", f"core API unreachable: {exc}", "start ostium-core.service")
    web = read_web_build(services.settings.paths.web_dist)
    core_version = str(core.get("core_version")) if core.get("core_version") else None
    web_version = str(web.get("version")) if web.get("available") and web.get("version") else None
    mismatches = version_mismatches(build.version, core=core_version, web=web_version)
    add(
        "version_consistency",
        "pass" if not mismatches else "fail",
        "control plane, core and Web bundle versions match"
        if not mismatches
        else "; ".join(
            f"{item['surface']} reports {item['actual']} (expected {item['expected']})"
            for item in mismatches
        ),
        None if not mismatches else "stop the stale process and reinstall the expected release",
        {
            "expected": build.version,
            "core": core_version,
            "web": web_version,
            "web_build": web,
            "mismatches": mismatches,
        },
    )
    engine = Path(services.settings.engine_path or services.settings.paths.engine_binary)
    if engine.is_file():
        add("engine", "pass", f"core binary found at {engine}")
    else:
        add("engine", "fail", f"core binary missing at {engine}", "run `ostium core install`")
    proxy = await asyncio.to_thread(lambda: services.proxy.status())
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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "system proxy is a client feature", "role_mismatch")
    if services.settings.tun_enabled and payload.enabled:
        raise ApiError(409, "TUN and system proxy are mutually exclusive", "mode_conflict")
    if payload.enabled:
        try:
            core = await services.engine.client.status()
        except Exception as exc:
            raise ApiError(
                409,
                f"connect the client core before enabling the system proxy: {exc}",
                "core_not_running",
            ) from exc
        if not core.get("running"):
            raise ApiError(
                409,
                "connect the client core before enabling the system proxy",
                "core_not_running",
            )
        try:
            result = await asyncio.to_thread(
                lambda: services.proxy.enable("127.0.0.1", services.settings.mixed_port)
            )
        except Exception as exc:
            raise ApiError(500, f"could not enable system proxy: {exc}", "proxy_failed") from exc
        services.settings.mode = Mode.SYSTEM_PROXY
        from ostium.services.settings import set_setting

        await set_setting(session, "client_paused", False)
        services.client_paused = False
    else:
        try:
            result = await asyncio.to_thread(lambda: services.proxy.disable())
        except Exception as exc:
            raise ApiError(500, f"could not disable system proxy: {exc}", "proxy_failed") from exc
        if services.settings.mode is Mode.SYSTEM_PROXY and not services.settings.tun_enabled:
            services.settings.mode = Mode.MIXED
    try:
        services.settings.save()
    except OSError as exc:
        if payload.enabled:
            try:
                await asyncio.to_thread(lambda: services.proxy.disable())
            except Exception:
                pass
        raise ApiError(
            500, f"could not persist the network mode: {exc}", "settings_write_failed"
        ) from exc
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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "TUN is a client feature", "role_mismatch")
    previous_tun = services.settings.tun_enabled
    previous_mode = services.settings.mode
    proxy_status = await asyncio.to_thread(lambda: services.proxy.status())
    proxy_was_enabled = bool(proxy_status.get("enabled"))
    if payload.enabled:
        if services.settings.allow_lan:
            raise ApiError(
                409,
                "disable Allow LAN before enabling TUN; the TUN LAN gateway is not supported",
                "mode_conflict",
            )
        if proxy_was_enabled:
            try:
                await asyncio.to_thread(lambda: services.proxy.disable())
            except Exception as exc:
                raise ApiError(
                    500, f"could not disable the system proxy: {exc}", "proxy_failed"
                ) from exc
        services.settings.tun_enabled = True
        services.settings.mode = Mode.TUN
        try:
            result = await services.engine.apply_client(session, mode="tun", tun_enabled=True)
        except Exception as exc:
            services.settings.tun_enabled = previous_tun
            services.settings.mode = previous_mode
            if proxy_was_enabled:
                try:
                    await asyncio.to_thread(
                        lambda: services.proxy.enable("127.0.0.1", services.settings.mixed_port)
                    )
                except Exception:
                    pass
            try:
                services.settings.save()
            except OSError:
                pass
            raise ApiError(500, f"TUN could not be enabled: {exc}", "tun_failed") from exc
        from ostium.services.settings import set_setting

        await set_setting(session, "client_paused", False)
        services.client_paused = False
        message = "TUN enabled"
    else:
        services.settings.tun_enabled = False
        services.settings.mode = Mode.MIXED
        try:
            result = await services.engine.apply_client(session, mode="mixed", tun_enabled=False)
        except Exception as exc:
            services.settings.tun_enabled = previous_tun
            services.settings.mode = previous_mode
            try:
                services.settings.save()
            except OSError:
                pass
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
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "connection modes are a client feature", "role_mismatch")
    try:
        mode = Mode(payload.mode)
    except ValueError as exc:
        raise ApiError(400, "mode must be mixed, system_proxy or tun", "bad_mode") from exc
    if mode is Mode.TUN:
        result = await toggle_tun(TunToggle(enabled=True), request, admin, services, session)
        return {"mode": "tun", **result}
    if services.settings.tun_enabled:
        await toggle_tun(TunToggle(enabled=False), request, admin, services, session)
    proxy_enabled = bool((await asyncio.to_thread(lambda: services.proxy.status())).get("enabled"))
    if mode is Mode.SYSTEM_PROXY:
        if not proxy_enabled:
            await toggle_proxy(ProxyToggle(enabled=True), request, admin, services, session)
    elif proxy_enabled:
        await toggle_proxy(ProxyToggle(enabled=False), request, admin, services, session)
    services.settings.mode = mode
    try:
        services.settings.save()
    except OSError:
        pass
    # toggle_tun()/toggle_proxy() already apply the client configuration when
    # they change it.  A separate best-effort apply here used to swallow core
    # failures and report success; there is no state left to apply.
    return {"mode": mode.value}


@router.post("/system/connect")
async def connect(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "connect is a client action", "role_mismatch")
    services.watchdog_suspended = False
    try:
        result = await services.engine.apply_client(session)
    except Exception as exc:
        code = getattr(exc, "code", "engine_error")
        status = getattr(exc, "status_code", 502)
        raise ApiError(status, str(exc), code) from exc
    from ostium.services.settings import set_setting

    await set_setting(session, "client_paused", False)
    services.client_paused = False
    # Persist the intent before restoring the OS proxy: if proxy restoration
    # fails, the core is still connected and a later restart must not treat
    # this as a disconnected client.
    await session.commit()
    if services.settings.mode is Mode.SYSTEM_PROXY:
        try:
            await asyncio.to_thread(
                lambda: services.proxy.enable("127.0.0.1", services.settings.mixed_port)
            )
        except Exception as exc:
            raise ApiError(
                502,
                f"core is running but the system proxy could not be restored: {exc}",
                "proxy_failed",
            ) from exc
    await audit(session, actor=admin.username, action="client.connect", ip=client_ip(request))
    return {"connected": True, "status": result.get("status")}


@router.post("/system/disconnect")
async def disconnect(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "disconnect is a client action", "role_mismatch")
    services.watchdog_suspended = True
    services.client_paused = True
    from ostium.services.settings import set_setting

    # Persist the operator's intent before touching the proxy or core.  A
    # control-plane restart must not auto-connect last-good after an explicit
    # Disconnect, even if stopping the core then fails.
    await set_setting(session, "client_paused", True)
    await session.commit()
    if (await asyncio.to_thread(lambda: services.proxy.status())).get("enabled"):
        try:
            await asyncio.to_thread(lambda: services.proxy.disable())
        except Exception as exc:
            # Leave the core running: stopping it with a still-active OS proxy
            # would silently break all system traffic.  The operation failed,
            # so the persisted intent must go back to "connected" as well;
            # otherwise a later restart would suppress auto-connect while the
            # OS proxy still points at the running core.
            services.watchdog_suspended = False
            services.client_paused = False
            await set_setting(session, "client_paused", False)
            await session.commit()
            raise ApiError(
                502,
                f"could not restore the system proxy; core left running: {exc}",
                "proxy_failed",
            ) from exc
    try:
        status = await services.engine.client.stop()
    except Exception as exc:
        raise ApiError(502, f"could not stop the core: {exc}", "core_error") from exc
    services.settings.tun_enabled = False
    if services.settings.mode is Mode.TUN:
        services.settings.mode = Mode.MIXED
    try:
        services.settings.save()
    except OSError:
        pass
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
    session: AsyncSession = Depends(get_session, scope="function"),
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
    session: AsyncSession = Depends(get_session, scope="function"),
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
    session: AsyncSession = Depends(get_session, scope="function"),
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
    from ostium.services.netguard import UnsafeUrlError, resolve_remote_url

    if not 1 <= port <= 65535:
        return {"ok": False, "host": host, "message": "port must be between 1 and 65535"}
    url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    try:
        # Resolve the hostname too: validating only literal addresses would
        # let a public hostname pivot this probe to loopback/metadata.  Keep
        # the validated addresses and connect to them directly; resolving the
        # hostname again in create_connection would reopen the rebinding TOCTOU.
        target = await asyncio.to_thread(
            resolve_remote_url, f"https://{url_host}:{port}", allow_private=False
        )
    except (UnsafeUrlError, ValueError) as exc:
        return {"ok": False, "host": host, "message": str(exc)}

    def probe() -> dict[str, Any]:
        context = ssl.create_default_context()
        last_error: Exception | None = None
        for address in target.addresses:
            candidate = address.split("%", 1)[0]
            try:
                with (
                    socket.create_connection((candidate, port), timeout=8) as sock,
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
                    "message": (
                        "TLS 1.3 handshake succeeded" if ok else "TLS 1.3 is required for Reality"
                    ),
                }
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError("the host resolved to no usable address")

    try:
        # Socket handshakes can block for up to eight seconds; never stall the
        # whole control-plane event loop while an operator probes a host.
        return await asyncio.to_thread(probe)
    except Exception as exc:
        return {"ok": False, "host": host, "message": str(exc)}
