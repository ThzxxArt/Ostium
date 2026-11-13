"""Authentication, initial setup and account security endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ostium import __version__
from ostium.api.deps import (
    Services,
    client_ip,
    get_current_admin,
    get_services,
    get_session,
    is_loopback,
)
from ostium.api.errors import ApiError
from ostium.config import Settings
from ostium.db.models import AdminUser
from ostium.services import auth as auth_service
from ostium.services.audit import audit
from ostium.services.settings import is_initialized, set_setting
from ostium.services.users import ensure_inbounds

router = APIRouter(tags=["auth"])
SESSION_COOKIE = "ostium_session"
CSRF_COOKIE = "ostium_csrf"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    totp: str | None = None
    recovery_code: str | None = Field(default=None, max_length=64)


class SetupRequest(BaseModel):
    role: str = "server"
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=10, max_length=200)
    domain: str | None = None
    public_ui: bool = False
    acme_email: str | None = None
    lines: Literal["reality", "later", "hysteria2", "both"] = "reality"


class PasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class TotpConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TotpDisable(BaseModel):
    password: str


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=auth_service.SESSION_ABSOLUTE_SECONDS,
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookies,
        path="/",
    )


@router.get("/auth/csrf")
async def csrf(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(CSRF_COOKIE) or getattr(request.state, "csrf_token", "")
    if not token:
        raise ApiError(500, "CSRF token could not be initialised", "csrf_unavailable")
    app = getattr(request, "app", None)
    services = getattr(getattr(app, "state", None), "services", None)
    secure = bool(getattr(getattr(services, "settings", None), "secure_cookies", False))
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=False,
        samesite="strict",
        secure=secure,
        path="/",
    )
    return {"csrf_token": token}


@router.get("/auth/status")
async def status(
    request: Request,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    initialized = await is_initialized(session)
    admin = await auth_service.get_admin(session)
    authenticated = False
    must_change = False
    totp_enabled = False
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        resolved = await auth_service.resolve_session(session, cookie)
        if resolved:
            authenticated = True
            must_change = resolved[0].must_change_password
            totp_enabled = bool(resolved[0].totp_secret_enc)
    return {
        "initialized": initialized,
        "has_admin": admin is not None,
        "authenticated": authenticated,
        "must_change_password": must_change,
        "totp_enabled": totp_enabled,
        "role": services.settings.role.value,
        "version": __version__,
        "public_ui": services.settings.public_ui,
    }


@router.post("/setup")
async def setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if await is_initialized(session) or await auth_service.get_admin(session) is not None:
        raise ApiError(409, "Ostium is already initialised", "already_initialized")
    if payload.role != services.settings.role.value:
        raise ApiError(
            400,
            f"this process is configured as {services.settings.role.value}; "
            f"run `ostium init --role {payload.role}` first",
            "role_mismatch",
        )
    if payload.public_ui:
        raise ApiError(
            400,
            "public UI cannot be enabled during setup; enable it after configuring TOTP",
            "totp_required",
        )
    admin = await auth_service.create_admin(
        session, username=payload.username, password=payload.password, must_change_password=False
    )
    if services.settings.role.value == "server":
        if payload.lines in {"hysteria2", "both"}:
            raise ApiError(
                409,
                "Hysteria2/Trojan require a TLS certificate before they can be enabled; "
                "complete setup with Reality, issue a certificate, then enable TLS lines",
                "certificate_required",
            )
        inbounds = await ensure_inbounds(session, services.store)
        if payload.lines == "later":
            for inbound in inbounds:
                inbound.enabled = False
    server_info = {
        "domain": payload.domain.strip().lower() if payload.domain else None,
        "public_host": payload.domain.strip().lower() if payload.domain else None,
        "public_ui": False,
        "acme_email": payload.acme_email,
        "lines": payload.lines,
    }
    await set_setting(session, "server", server_info)
    await set_setting(session, "initialized", True)
    await set_setting(session, "initialized_at", datetime.now(UTC).isoformat())
    await audit(
        session,
        actor=admin.username,
        action="setup.completed",
        target=services.settings.role.value,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        detail={"role": services.settings.role.value, "domain": server_info["domain"]},
    )
    token, _ = await auth_service.create_session(
        session,
        admin,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    await session.commit()
    _set_session_cookie(response, token, services.settings)
    return {"ok": True, "role": services.settings.role.value, "username": admin.username}


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if not await is_initialized(session):
        raise ApiError(409, "Ostium has not been initialised", "not_initialized")
    ip = client_ip(request)
    try:
        admin = await auth_service.authenticate(
            session,
            services.settings,
            username=payload.username,
            password=payload.password,
            totp_code=payload.totp,
            recovery_code=payload.recovery_code,
            ip=ip,
        )
    except auth_service.AuthError as exc:
        await audit(
            session,
            actor=payload.username[:100],
            action="auth.login_failed",
            ip=ip,
            user_agent=request.headers.get("user-agent", ""),
            detail={"code": exc.code},
        )
        # Persist the failed-attempt counter and audit trail even though the
        # request fails; the generic dependency would otherwise roll them back.
        await session.commit()
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    token, _ = await auth_service.create_session(
        session,
        admin,
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    await audit(
        session,
        actor=admin.username,
        action="auth.login",
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    await session.commit()
    _set_session_cookie(response, token, services.settings)
    return {
        "ok": True,
        "username": admin.username,
        "must_change_password": admin.must_change_password,
        "totp_enabled": bool(admin.totp_secret_enc),
    }


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        resolved = await auth_service.resolve_session(session, cookie)
        if resolved:
            await auth_service.revoke_session(session, resolved[1])
            await audit(
                session, actor=resolved[0].username, action="auth.logout", ip=client_ip(request)
            )
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return {
        "id": admin.id,
        "username": admin.username,
        "must_change_password": admin.must_change_password,
        "totp_enabled": bool(admin.totp_secret_enc),
        "recovery_codes_remaining": len(admin.recovery_codes_hash),
        "last_login_at": admin.last_login_at.isoformat() if admin.last_login_at else None,
        "role": services.settings.role.value,
    }


@router.post("/auth/password")
async def change_password(
    payload: PasswordRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if not await auth_service.check_password(admin, payload.current_password):
        raise ApiError(403, "current password is incorrect", "invalid_password")
    await auth_service.set_password(session, admin, payload.new_password)
    revoked = await auth_service.revoke_other_sessions(
        session, admin, request.cookies.get(SESSION_COOKIE)
    )
    await audit(
        session,
        actor=admin.username,
        action="auth.password_changed",
        ip=client_ip(request),
        detail={"sessions_revoked": revoked},
    )
    return {"ok": True, "sessions_revoked": revoked}


@router.post("/auth/totp/start")
async def totp_start(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    secret, uri, codes = auth_service.start_totp(admin, services.settings)
    await session.flush()
    await audit(session, actor=admin.username, action="auth.totp_started", ip=client_ip(request))
    return {"secret": secret, "uri": uri, "recovery_codes": codes}


@router.post("/auth/totp/confirm")
async def totp_confirm(
    payload: TotpConfirm,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    try:
        auth_service.confirm_totp(admin, services.settings, payload.code)
    except auth_service.AuthError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    await audit(session, actor=admin.username, action="auth.totp_enabled", ip=client_ip(request))
    return {"ok": True}


@router.post("/auth/totp/cancel")
async def totp_cancel(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Abandon a pending TOTP enrollment without changing login policy."""

    auth_service.cancel_totp(admin)
    await audit(session, actor=admin.username, action="auth.totp_cancelled", ip=client_ip(request))
    return {"ok": True}


@router.get("/auth/local-login")
async def local_login(
    token: str,
    request: Request,
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Response:
    from fastapi.responses import RedirectResponse

    if not is_loopback(request):
        raise ApiError(403, "local login links are loopback-only", "loopback_required")
    if not auth_service.consume_local_login_token(services.settings, token):
        raise ApiError(
            401, "local login link is invalid, expired or already used", "local_login_invalid"
        )
    admin = await auth_service.get_admin(session)
    if admin is None:
        raise ApiError(409, "Ostium is not initialised", "not_initialized")
    session_token, _ = await auth_service.create_session(
        session,
        admin,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    await session.commit()
    redirect = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(redirect, session_token, services.settings)
    return redirect


@router.post("/auth/totp/disable")
async def totp_disable(
    payload: TotpDisable,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    if not await auth_service.check_password(admin, payload.password):
        raise ApiError(403, "password is incorrect", "invalid_password")
    if services.settings.public_ui:
        raise ApiError(409, "TOTP is mandatory while the public UI is enabled", "totp_required")
    await auth_service.disable_totp(session, admin)
    await audit(session, actor=admin.username, action="auth.totp_disabled", ip=client_ip(request))
    return {"ok": True}
