"""Application settings, public UI policy and API tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium import __version__
from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, ApiToken, Certificate
from ostium.services.audit import audit
from ostium.services.settings import all_settings, get_setting, set_setting
from ostium.util.time import iso

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    log_level: str | None = None
    mixed_port: int | None = Field(default=None, ge=1024, le=65535)
    routing_mode: str | None = None
    trusted_hosts: list[str] | None = None
    auto_connect: bool | None = None
    auto_reconnect: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    update_channel: str | None = None
    audit_retention_days: int | None = Field(default=None, ge=7, le=3650)
    traffic_retention_days: int | None = Field(default=None, ge=30, le=3650)
    auto_backup: bool | None = None
    notifications_enabled: bool | None = None


class PublicUiRequest(BaseModel):
    enabled: bool
    domain: str | None = None


class TokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_at: datetime | None = None


@router.get("/settings")
async def read_settings(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stored = await all_settings(session)
    server_info = stored.get("server", {}) if isinstance(stored.get("server"), dict) else {}
    routing_mode = await get_setting(session, "routing_mode", "smart")
    public = {
        "general": {
            "role": services.settings.role.value,
            "version": __version__,
            "log_level": services.settings.log_level,
            "mixed_port": services.settings.mixed_port,
            "mode": services.settings.mode.value,
            "routing_mode": routing_mode,
            "tun_enabled": services.settings.tun_enabled,
            "auto_connect": services.settings.auto_connect,
            "auto_reconnect": services.settings.auto_reconnect,
            "public_ui": services.settings.public_ui,
            "domain": server_info.get("domain"),
            "acme_email": services.settings.acme_email,
            "acme_staging": services.settings.acme_staging,
        },
        "security": {
            "secure_cookies": services.settings.secure_cookies,
            "trusted_hosts": services.settings.trusted_hosts,
            "api_tokens": await _list_tokens(session),
        },
        "notifications": {
            "webhook_url": stored.get("webhook_url"),
            "has_webhook_secret": bool(stored.get("webhook_secret")),
            "enabled": stored.get("notifications_enabled", True),
        },
        "maintenance": {
            "update_channel": stored.get("update_channel", "stable"),
            "audit_retention_days": stored.get("audit_retention_days", 90),
            "traffic_retention_days": stored.get("traffic_retention_days", 365),
            "auto_backup": stored.get("auto_backup", False),
        },
    }
    return public


@router.patch("/settings")
async def update_settings(
    payload: SettingsPatch,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("mixed_port"):
        services.settings.mixed_port = changes["mixed_port"]
    if changes.get("log_level"):
        services.settings.log_level = changes["log_level"]
    if "trusted_hosts" in changes and changes["trusted_hosts"] is not None:
        services.settings.trusted_hosts = changes["trusted_hosts"]
    if changes.get("routing_mode"):
        await set_setting(session, "routing_mode", changes["routing_mode"])
    if changes.get("auto_connect") is not None:
        services.settings.auto_connect = bool(changes["auto_connect"])
    if changes.get("auto_reconnect") is not None:
        services.settings.auto_reconnect = bool(changes["auto_reconnect"])
    for key in (
        "webhook_url",
        "update_channel",
        "audit_retention_days",
        "traffic_retention_days",
        "auto_backup",
        "notifications_enabled",
    ):
        if key in changes and changes[key] is not None:
            await set_setting(session, key, changes[key])
    if "webhook_secret" in changes and changes["webhook_secret"] is not None:
        await set_setting(session, "webhook_secret", changes["webhook_secret"])
    try:
        services.settings.save()
    except OSError as exc:
        raise ApiError(500, f"could not persist settings: {exc}", "settings_write_failed") from exc
    await audit(
        session,
        actor=admin.username,
        action="settings.updated",
        ip=client_ip(request),
        detail={"fields": sorted(changes)},
    )
    applied: dict[str, Any] = {}
    if services.settings.role.value == "client" and (
        "mixed_port" in changes or "log_level" in changes or "routing_mode" in changes
    ):
        try:
            result = await services.engine.apply_client(session)
            applied = {"applied": True, "revision": result["status"].get("revision")}
        except Exception as exc:
            applied = {"applied": False, "warning": str(exc)}
    return {"ok": True, "restart_required": "mixed_port" in changes, **applied}


@router.post("/settings/public-ui")
async def public_ui(
    payload: PublicUiRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.enabled:
        if not admin.totp_secret_enc:
            raise ApiError(
                409, "enable TOTP before exposing the admin UI publicly", "totp_required"
            )
        if not payload.domain:
            raise ApiError(400, "a domain is required for the public UI", "domain_required")
        certificate = (
            await session.execute(select(Certificate).where(Certificate.domain == payload.domain))
        ).scalar_one_or_none()
        if certificate is None:
            raise ApiError(
                409, "issue or upload a certificate for this domain first", "certificate_required"
            )
        services.settings.public_ui = True
        services.settings.secure_cookies = True
        services.settings.trusted_hosts = list({*services.settings.trusted_hosts, payload.domain})
        server_info = await get_setting(session, "server", {})
        if not isinstance(server_info, dict):
            server_info = {}
        server_info.update({"domain": payload.domain, "public_ui": True})
        await set_setting(session, "server", server_info)
    else:
        services.settings.public_ui = False
        services.settings.secure_cookies = False
    try:
        services.settings.save()
    except OSError as exc:
        raise ApiError(500, f"could not persist settings: {exc}", "settings_write_failed") from exc
    await audit(
        session,
        actor=admin.username,
        action="settings.public_ui",
        target=str(payload.enabled),
        ip=client_ip(request),
    )
    return {
        "public_ui": services.settings.public_ui,
        "restart_required": True,
        "message": "Restart ostium.service to apply the new listener/TLS settings.",
    }


@router.get("/api-tokens")
async def list_tokens(
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"tokens": await _list_tokens(session)}


@router.post("/api-tokens", status_code=201)
async def create_token(
    payload: TokenRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from ostium.services.auth import create_api_token

    token, row = await create_api_token(
        session, name=payload.name, scopes=payload.scopes, expires_at=payload.expires_at
    )
    await audit(
        session,
        actor=admin.username,
        action="api_token.created",
        target=payload.name,
        ip=client_ip(request),
    )
    return {
        "token": token,
        "id": row.id,
        "name": row.name,
        "scopes": row.scopes,
        "expires_at": iso(row.expires_at),
    }


@router.delete("/api-tokens/{token_id}")
async def revoke_token(
    token_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    row = await session.get(ApiToken, token_id)
    if row is None:
        raise ApiError(404, "token not found", "not_found")
    row.revoked = True
    await audit(
        session,
        actor=admin.username,
        action="api_token.revoked",
        target=row.name,
        ip=client_ip(request),
    )
    return {"revoked": True}


async def _list_tokens(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (await session.execute(select(ApiToken).order_by(ApiToken.created_at.desc())))
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "scopes": row.scopes,
            "created_at": iso(row.created_at),
            "expires_at": iso(row.expires_at),
            "last_used_at": iso(row.last_used_at),
            "revoked": row.revoked,
        }
        for row in rows
    ]
