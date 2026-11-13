"""Server line (inbound) management."""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, Certificate, Inbound
from ostium.engine.manager import EngineError
from ostium.services.audit import audit
from ostium.services.certificates import serialize_certificate
from ostium.services.users import inbound_params
from ostium.util.ids import new_short_id
from ostium.util.time import iso

router = APIRouter(tags=["inbounds"])
KINDS = {"vless", "hysteria2", "trojan", "shadowsocks"}
TCP_KINDS = {"vless", "trojan", "shadowsocks"}
DEFAULT_PORTS = {"vless": 443, "hysteria2": 443, "trojan": 443, "shadowsocks": 8388}
RESERVED_PORTS = {8788, 19090, 19091}


class InboundPatch(BaseModel):
    enabled: bool | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    certificate_id: str | None = None
    reality_server_name: str | None = None
    reality_handshake_server: str | None = None
    reality_handshake_port: int | None = Field(default=None, ge=1, le=65535)
    obfs_password: str | None = None


async def _get_inbound(session: AsyncSession, kind: str) -> Inbound:
    inbound = (
        await session.execute(select(Inbound).where(Inbound.kind == kind))
    ).scalar_one_or_none()
    if inbound is None:
        raise ApiError(404, f"inbound {kind!r} does not exist", "not_found")
    return inbound


def _serialize(
    inbound: Inbound,
    params: dict[str, Any],
    certificate: Certificate | None,
    *,
    skipped_reason: str | None = None,
    port_conflict: str | None = None,
) -> dict[str, Any]:
    return {
        "id": inbound.id,
        "kind": inbound.kind,
        "enabled": inbound.enabled,
        "active": inbound.enabled and skipped_reason is None,
        "listen": inbound.listen,
        "port": inbound.port,
        "default_port": DEFAULT_PORTS.get(inbound.kind, inbound.port),
        "params": {
            "public_key": params.get("public_key"),
            "short_id": params.get("short_id"),
            "server_name": params.get("server_name"),
            "handshake_server": params.get("handshake_server"),
            "handshake_port": params.get("handshake_port"),
            "has_obfs": bool(params.get("obfs_password")),
            "has_server_key": bool(params.get("server_key")),
        },
        "certificate": serialize_certificate(certificate) if certificate else None,
        "requires_certificate": inbound.kind in {"hysteria2", "trojan"},
        "skipped_reason": skipped_reason,
        "port_conflict": port_conflict,
        "updated_at": iso(inbound.updated_at),
    }


def _skipped_reason(
    inbound: Inbound,
    params: dict[str, Any],
    certificate: Certificate | None,
) -> str | None:
    if not inbound.enabled:
        return None
    if inbound.kind == "vless" and not params.get("private_key"):
        return "Reality private key is missing; rotate the keys"
    if inbound.kind in {"hysteria2", "trojan"}:
        if certificate is None:
            return "no certificate is assigned to this inbound"
        if certificate.status != "ready" or certificate.expires_at is None:
            return "the assigned certificate is not ready"
        from ostium.util.time import as_utc, utcnow

        if as_utc(certificate.expires_at) <= utcnow():
            return "the assigned certificate has expired"
    return None


def _conflict_map(rows: list[Inbound]) -> dict[str, str]:
    by_port: dict[int, list[str]] = {}
    for inbound in rows:
        if inbound.enabled and inbound.kind in TCP_KINDS:
            by_port.setdefault(inbound.port, []).append(inbound.kind)
    return {
        kind: f"TCP port {port} is also used by {', '.join(other)}"
        for port, kinds in by_port.items()
        if len(kinds) > 1
        for kind in kinds
        for other in [sorted(item for item in kinds if item != kind)]
        if other
    }


@router.get("/inbounds")
async def list_inbounds(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (await session.execute(select(Inbound).order_by(Inbound.kind))).scalars().all()
    certs = {cert.id: cert for cert in (await session.execute(select(Certificate))).scalars().all()}
    conflicts = _conflict_map(list(rows))
    return {
        "inbounds": [
            _serialize(
                row,
                inbound_params(row, services.store),
                certs.get(row.certificate_id or ""),
                skipped_reason=_skipped_reason(
                    row, inbound_params(row, services.store), certs.get(row.certificate_id or "")
                ),
                port_conflict=conflicts.get(row.kind),
            )
            for row in rows
        ]
    }


@router.patch("/inbounds/{kind}")
async def update_inbound(
    kind: str,
    payload: InboundPatch,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ApiError(404, f"unknown inbound {kind!r}", "not_found")
    inbound = await _get_inbound(session, kind)
    params = inbound_params(inbound, services.store)
    changes = payload.model_dump(exclude_unset=True)
    if "port" in changes and changes["port"] is not None:
        port = int(changes["port"])
        # Hysteria2 is QUIC/UDP, so it may share a port number with TCP
        # listeners.  All other inbounds are TCP and must not collide.
        if port in RESERVED_PORTS or port == int(services.settings.port):
            raise ApiError(
                409,
                f"port {port} is reserved by the core API or the admin UI",
                "port_reserved",
            )
        if kind in TCP_KINDS:
            others = (
                (
                    await session.execute(
                        select(Inbound).where(
                            Inbound.id != inbound.id,
                            Inbound.enabled.is_(True),
                            Inbound.port == port,
                            Inbound.kind.in_(TCP_KINDS),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if others:
                raise ApiError(
                    409,
                    f"TCP port {port} is already used by {', '.join(row.kind for row in others)}",
                    "port_conflict",
                )
        inbound.port = port
        if port not in services.settings.proxy_ports:
            services.settings.proxy_ports = sorted({*services.settings.proxy_ports, port})
            try:
                services.settings.save()
            except OSError as exc:
                raise ApiError(
                    500,
                    f"could not persist the approved proxy port: {exc}",
                    "settings_write_failed",
                ) from exc
    if "enabled" in changes and changes["enabled"] is not None:
        enabled = bool(changes["enabled"])
        if enabled and kind in {"hysteria2", "trojan"}:
            certificate = await _resolve_certificate(
                session, inbound, changes.get("certificate_id")
            )
            if certificate is None:
                raise ApiError(
                    409,
                    f"{kind} requires a TLS certificate; issue or upload one first",
                    "certificate_required",
                )
            inbound.certificate_id = certificate.id
        if enabled and kind == "trojan":
            vless = await _get_inbound(session, "vless")
            vless.enabled = False
        if enabled and kind == "vless":
            trojan = await _get_inbound(session, "trojan")
            trojan.enabled = False
        inbound.enabled = enabled
    if changes.get("certificate_id"):
        if kind not in {"hysteria2", "trojan"}:
            raise ApiError(400, "only TLS inbounds accept a certificate", "bad_request")
        certificate = await _resolve_certificate(session, inbound, changes["certificate_id"])
        if certificate is None:
            raise ApiError(404, "certificate not found", "not_found")
        inbound.certificate_id = certificate.id
    if kind == "vless":
        if payload.reality_server_name:
            params["server_name"] = payload.reality_server_name
        if payload.reality_handshake_server:
            params["handshake_server"] = payload.reality_handshake_server
        if payload.reality_handshake_port:
            params["handshake_port"] = payload.reality_handshake_port
    if kind == "hysteria2" and payload.obfs_password is not None:
        params["obfs_password"] = payload.obfs_password or None
    if params:
        inbound.params_enc = services.store.encrypt(
            json.dumps(params), table="inbounds", record_id=inbound.id, field="params"
        )
    await session.flush()
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="inbound.updated",
        target=kind,
        ip=client_ip(request),
        detail={
            "changes": {key: value for key, value in changes.items() if key != "obfs_password"}
        },
    )
    return {
        "inbound": _serialize(
            inbound,
            params,
            await _certificate_for(session, inbound),
            skipped_reason=_skipped_reason(
                inbound, params, await _certificate_for(session, inbound)
            ),
        ),
        **applied,
    }


@router.post("/inbounds/{kind}/reality-keys")
async def rotate_reality_keys(
    kind: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if kind != "vless":
        raise ApiError(400, "only Reality uses X25519 keys", "bad_request")
    inbound = await _get_inbound(session, kind)
    params = inbound_params(inbound, services.store)
    private_key = X25519PrivateKey.generate()
    private_raw = private_key.private_bytes_raw()
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    params["private_key"] = base64.urlsafe_b64encode(private_raw).decode().rstrip("=")
    params["public_key"] = base64.urlsafe_b64encode(public_raw).decode().rstrip("=")
    params["short_id"] = new_short_id(8)
    inbound.params_enc = services.store.encrypt(
        json.dumps(params), table="inbounds", record_id=inbound.id, field="params"
    )
    await session.flush()
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="inbound.reality_keys_rotated",
        target=kind,
        ip=client_ip(request),
    )
    return {"params": params, **applied}


async def _resolve_certificate(
    session: AsyncSession, inbound: Inbound, certificate_id: str | None
) -> Certificate | None:
    from ostium.services.certificates import select_ready_certificate

    if certificate_id:
        return await select_ready_certificate(session, certificate_id)
    if inbound.certificate_id:
        return await select_ready_certificate(session, inbound.certificate_id)
    return None


async def _certificate_for(session: AsyncSession, inbound: Inbound) -> Certificate | None:
    if not inbound.certificate_id:
        return None
    return await session.get(Certificate, inbound.certificate_id)


async def _apply_server(services: Services, session: AsyncSession) -> dict[str, Any]:
    try:
        result = await services.engine.apply_server(session)
        return {"applied": True, "revision": result["status"].get("revision")}
    except EngineError as exc:
        if exc.code in {"core_unavailable", "core_unreachable", "engine_unavailable"}:
            return {"applied": False, "warning": str(exc)}
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
