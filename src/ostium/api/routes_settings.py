"""Application settings, public UI policy and API tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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
from ostium.util.time import as_utc, iso, utcnow

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    log_level: str | None = None
    mixed_port: int | None = Field(default=None, ge=1024, le=65535)
    allow_lan: bool | None = None
    routing_mode: str | None = None
    trusted_hosts: list[str] | None = None
    ui_allowlist: list[str] | None = None
    auto_connect: bool | None = None
    auto_reconnect: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    update_channel: str | None = None
    audit_retention_days: int | None = Field(default=None, ge=7, le=3650)
    traffic_retention_days: int | None = Field(default=None, ge=30, le=3650)
    job_retention_days: int | None = Field(default=None, ge=1, le=365)
    auto_backup: bool | None = None
    notifications_enabled: bool | None = None
    public_base_url: str | None = Field(default=None, max_length=500)
    acme_email: str | None = Field(default=None, max_length=254)
    acme_staging: bool | None = None
    block_private_egress: bool | None = None


class PublicUiRequest(BaseModel):
    enabled: bool
    domain: str | None = None


def _default_scopes() -> list[Literal["read", "write"]]:
    return ["read", "write"]


class TokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Literal["read", "write"]] = Field(
        default_factory=_default_scopes, min_length=1, max_length=2
    )
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
            "allow_lan": services.settings.allow_lan,
            "mode": services.settings.mode.value,
            "routing_mode": routing_mode,
            "tun_enabled": services.settings.tun_enabled,
            "auto_connect": services.settings.auto_connect,
            "auto_reconnect": services.settings.auto_reconnect,
            "public_ui": services.settings.public_ui,
            "domain": server_info.get("domain"),
            "acme_email": services.settings.acme_email,
            "acme_staging": services.settings.acme_staging,
            "public_base_url": stored.get("public_base_url"),
            "block_private_egress": services.settings.block_private_egress,
        },
        "security": {
            "secure_cookies": services.settings.secure_cookies,
            "trusted_hosts": services.settings.trusted_hosts,
            "ui_allowlist": services.settings.ui_allowlist,
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
            "job_retention_days": stored.get("job_retention_days", 7),
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
    previous_allow_lan = services.settings.allow_lan
    if changes.get("allow_lan") is True and (
        services.settings.tun_enabled or services.settings.mode.value == "tun"
    ):
        raise ApiError(
            409,
            "LAN sharing is only available in mixed or system-proxy mode; disable TUN first",
            "mode_conflict",
        )
    if changes.get("mixed_port"):
        services.settings.mixed_port = changes["mixed_port"]
    if "public_base_url" in changes:
        from ostium.services.public_url import normalize_base_url

        raw_value = changes["public_base_url"]
        value = str(raw_value).strip() if raw_value is not None else ""
        if value:
            try:
                await set_setting(session, "public_base_url", normalize_base_url(value))
            except ValueError as exc:
                raise ApiError(400, str(exc), "invalid_public_base_url") from exc
        else:
            # An explicit null from the UI clears a previously configured URL.
            await set_setting(session, "public_base_url", None)
    if "acme_email" in changes:
        raw_email = changes["acme_email"]
        services.settings.acme_email = str(raw_email).strip() if raw_email else None
    if changes.get("acme_staging") is not None:
        services.settings.acme_staging = bool(changes["acme_staging"])
    if changes.get("block_private_egress") is not None:
        services.settings.block_private_egress = bool(changes["block_private_egress"])
    if changes.get("allow_lan") is not None:
        services.settings.allow_lan = bool(changes["allow_lan"])
    if changes.get("log_level"):
        level = str(changes["log_level"]).lower()
        if level not in {"debug", "info", "warning", "error"}:
            raise ApiError(400, "log_level must be debug, info, warning or error", "bad_log_level")
        services.settings.log_level = level
    if "trusted_hosts" in changes and changes["trusted_hosts"] is not None:
        hosts = [str(item).strip() for item in changes["trusted_hosts"]]
        if any(not item or item == "*" for item in hosts):
            raise ApiError(
                400,
                "trusted_hosts cannot contain empty entries or a wildcard",
                "invalid_trusted_hosts",
            )
        services.settings.trusted_hosts = hosts
    if "ui_allowlist" in changes and changes["ui_allowlist"] is not None:
        import ipaddress

        validated: list[str] = []
        for entry in changes["ui_allowlist"]:
            try:
                validated.append(str(ipaddress.ip_network(entry, strict=False)))
            except ValueError as exc:
                raise ApiError(
                    400, f"invalid CIDR in ui_allowlist: {entry}", "invalid_allowlist"
                ) from exc
        services.settings.ui_allowlist = validated
    if changes.get("routing_mode"):
        routing_mode = str(changes["routing_mode"])
        if routing_mode not in {"smart", "direct", "global", "custom"}:
            raise ApiError(
                400,
                "routing_mode must be smart, direct, global or custom",
                "bad_routing_mode",
            )
        await set_setting(session, "routing_mode", routing_mode)
    if changes.get("auto_connect") is not None:
        services.settings.auto_connect = bool(changes["auto_connect"])
    if changes.get("auto_reconnect") is not None:
        services.settings.auto_reconnect = bool(changes["auto_reconnect"])
    if "webhook_url" in changes:
        raw_url = changes["webhook_url"]
        value = str(raw_url).strip() if raw_url else ""
        if value:
            from urllib.parse import urlparse

            from ostium.services.netguard import UnsafeUrlError, validate_target_host

            parsed = urlparse(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ApiError(
                    400,
                    "webhook_url must be an absolute http(s) URL without credentials",
                    "bad_webhook",
                )
            try:
                validate_target_host(parsed.hostname, allow_private=False)
            except UnsafeUrlError as exc:
                raise ApiError(400, str(exc), "bad_webhook") from exc
        await set_setting(session, "webhook_url", value or None)
    if "update_channel" in changes and changes["update_channel"] is not None:
        channel = str(changes["update_channel"])
        if channel not in {"stable", "beta"}:
            raise ApiError(400, "update_channel must be stable or beta", "bad_update_channel")
        await set_setting(session, "update_channel", channel)
    for key in (
        "audit_retention_days",
        "traffic_retention_days",
        "job_retention_days",
        "auto_backup",
        "notifications_enabled",
    ):
        if key in changes and changes[key] is not None:
            await set_setting(session, key, changes[key])
    if "webhook_secret" in changes:
        raw_secret = changes["webhook_secret"]
        await set_setting(session, "webhook_secret", str(raw_secret) if raw_secret else None)
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
        "mixed_port" in changes
        or "allow_lan" in changes
        or "log_level" in changes
        or "routing_mode" in changes
    ):
        try:
            result = await services.engine.apply_client(session)
            applied = {"applied": True, "revision": result["status"].get("revision")}
        except Exception as exc:
            if "allow_lan" in changes:
                # The switch must reflect reality: never leave the UI showing
                # "off" while sing-box still listens on 0.0.0.0 (or vice versa).
                services.settings.allow_lan = previous_allow_lan
                try:
                    services.settings.save()
                except OSError:
                    pass
                raise ApiError(
                    502,
                    f"LAN sharing could not be applied: {exc}",
                    "lan_apply_failed",
                ) from exc
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
    server_info = await get_setting(session, "server", {})
    if not isinstance(server_info, dict):
        server_info = {}
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
        from pathlib import Path

        if (
            certificate is None
            or certificate.status != "ready"
            or certificate.expires_at is None
            or as_utc(certificate.expires_at) <= utcnow()
            or not Path(certificate.cert_path).is_file()
            or not Path(certificate.key_path).is_file()
        ):
            raise ApiError(
                409,
                "issue or upload a ready certificate for this domain first",
                "certificate_required",
            )
        services.settings.public_ui = True
        services.settings.secure_cookies = True
        services.settings.trusted_hosts = list({*services.settings.trusted_hosts, payload.domain})
        from ostium.config import is_loopback_host

        if is_loopback_host(services.settings.host):
            # The toggle promises a reachable public listener.  A loopback
            # listener with TLS would still be unreachable from the internet,
            # so widen only in this explicit, certificate+TOTP-gated flow and
            # remember that the change was automatic.
            services.settings.host = "0.0.0.0"
            server_info["public_ui_auto_host"] = True
        server_info.update({"domain": payload.domain, "public_ui": True})
        await set_setting(session, "server", server_info)
        if not await get_setting(session, "public_base_url"):
            await set_setting(session, "public_base_url", f"https://{payload.domain}")
    else:
        services.settings.public_ui = False
        services.settings.secure_cookies = False
        auto_host = bool(server_info.pop("public_ui_auto_host", False))
        if auto_host and services.settings.host == "0.0.0.0":
            services.settings.host = "127.0.0.1"
        server_info["public_ui"] = False
        await set_setting(session, "server", server_info)
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
