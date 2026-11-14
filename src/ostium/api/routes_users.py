"""Proxy user management and subscription administration."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, ProxyUser
from ostium.domain.endpoints import ProfileDocument
from ostium.engine.manager import EngineError
from ostium.services.audit import audit
from ostium.services.stats import usage_series
from ostium.services.subscriptions import build_endpoints, subscription_payload
from ostium.services.users import (
    UserError,
    create_user,
    decrypt_subscription_token,
    endpoints_for_user,
    reset_usage,
    rotate_credentials,
    rotate_subscription,
    serialize_user,
    server_hostname,
    status_of,
)
from ostium.util.time import iso, utcnow

router = APIRouter(tags=["users"])


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None
    quota_bytes: int = Field(default=0, ge=0)
    quota_cycle: Literal["total", "monthly"] = "total"
    note: str = Field(default="", max_length=500)


class UserPatch(BaseModel):
    enabled: bool | None = None
    expires_at: datetime | None = None
    quota_bytes: int | None = Field(default=None, ge=0)
    quota_cycle: Literal["total", "monthly"] | None = None
    note: str | None = Field(default=None, max_length=500)


class RotateRequest(BaseModel):
    rotate_subscription: bool = False


class BulkRequest(BaseModel):
    action: Literal["enable", "disable", "delete", "rotate", "export"]
    ids: list[str] = Field(min_length=1, max_length=500)


def _online_names(services: Services) -> set[str]:
    if services.stats is None:
        return set()
    snapshot = services.stats.snapshot()
    users = cast(list[dict[str, Any]], snapshot.get("users", []))
    return {str(item["name"]) for item in users if item.get("online")}


async def _public_base_url(session: AsyncSession, services: Services) -> str:
    from ostium.services.public_url import public_base_url

    return await public_base_url(session, services.settings)


async def _get_user(session: AsyncSession, user_id: str) -> ProxyUser:
    user = await session.get(ProxyUser, user_id)
    if user is None:
        raise ApiError(404, "user not found", "not_found")
    return user


async def _apply_server(services: Services, session: AsyncSession) -> dict[str, Any]:
    try:
        result = await services.engine.apply_server(session)
        return {"applied": True, "revision": result["status"].get("revision")}
    except EngineError as exc:
        if exc.code in {"core_unavailable", "core_unreachable", "engine_unavailable"}:
            return {"applied": False, "warning": str(exc)}
        raise ApiError(exc.status_code, str(exc), exc.code) from exc


@router.get("/users")
async def list_users(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    users = (
        (await session.execute(select(ProxyUser).order_by(ProxyUser.created_at))).scalars().all()
    )
    online = _online_names(services)
    return {
        "users": [serialize_user(user, online=user.name in online) for user in users],
        "total": len(users),
    }


@router.post("/users", status_code=201)
async def add_user(
    payload: UserCreate,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        user, password, token = await create_user(
            session,
            services.store,
            name=payload.name,
            expires_at=payload.expires_at,
            quota_bytes=payload.quota_bytes,
            quota_cycle=payload.quota_cycle,
            note=payload.note,
        )
    except UserError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="user.created",
        target=user.name,
        ip=client_ip(request),
        detail={"quota_bytes": user.quota_bytes, "quota_cycle": user.quota_cycle},
    )
    data = await subscription_payload(
        session,
        services.store,
        user,
        base_url=await _public_base_url(session, services),
        token=token,
    )
    return {
        "user": serialize_user(user),
        "subscription": data,
        "password_once": password,
        **applied,
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    online = user.name in _online_names(services)
    pending = services.stats.pending_bytes(user.id) if services.stats is not None else 0
    return {"user": serialize_user(user, online=online), "pending_bytes": pending}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: UserPatch,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    changes = payload.model_dump(exclude_unset=True)
    if "enabled" in changes and changes["enabled"] is not None:
        user.enabled = bool(changes["enabled"])
        if user.enabled:
            user.disabled_reason = None
    if "expires_at" in changes:
        user.expires_at = changes["expires_at"]
    if "quota_bytes" in changes and changes["quota_bytes"] is not None:
        user.quota_bytes = changes["quota_bytes"]
    if "quota_cycle" in changes and changes["quota_cycle"] is not None:
        user.quota_cycle = changes["quota_cycle"]
    if "note" in changes:
        user.note = (changes["note"] or "")[:500]
    await session.flush()
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="user.updated",
        target=user.name,
        ip=client_ip(request),
        detail={"fields": sorted(changes)},
    )
    return {"user": serialize_user(user), **applied}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    name = user.name
    await session.delete(user)
    await session.flush()
    applied = await _apply_server(services, session)
    await audit(
        session, actor=admin.username, action="user.deleted", target=name, ip=client_ip(request)
    )
    return {"deleted": True, **applied}


@router.post("/users/{user_id}/rotate")
async def rotate_user(
    user_id: str,
    payload: RotateRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    await rotate_credentials(session, services.store, user)
    token = None
    if payload.rotate_subscription:
        token = await rotate_subscription(session, services.store, user)
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="user.credentials_rotated",
        target=user.name,
        ip=client_ip(request),
        detail={"subscription_rotated": payload.rotate_subscription},
    )
    result: dict[str, Any] = {
        "ok": True,
        "subscription_rotated": payload.rotate_subscription,
        **applied,
    }
    if token:
        result["subscription_token"] = token
    return result


@router.post("/users/{user_id}/reset-usage")
async def reset_user_usage(
    user_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    await reset_usage(session, user)
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="user.usage_reset",
        target=user.name,
        ip=client_ip(request),
    )
    return {"user": serialize_user(user), **applied}


@router.get("/users/{user_id}/usage")
async def user_usage(
    user_id: str,
    days: int = 30,
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    series = await usage_series(session, days=max(1, min(days, 365)), user_id=user.id)
    return {
        "user": serialize_user(user),
        "series": series,
        "today": series[-1] if series else {"up": 0, "down": 0},
    }


@router.get("/users/{user_id}/subscription")
async def get_subscription(
    user_id: str,
    request: Request,
    reveal: bool = False,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    token = decrypt_subscription_token(user, services.store)
    hint = f"{token[:6]}…{token[-4:]}" if token and len(token) > 12 else None
    if not reveal:
        return {
            "user": user.name,
            "has_token": token is not None,
            "token_hint": hint,
            "reveal_required": True,
            "status": status_of(user),
        }
    if token is None:
        token = await rotate_subscription(session, services.store, user)
    await audit(
        session,
        actor=admin.username,
        action="user.subscription_revealed",
        target=user.name,
        ip=client_ip(request),
    )
    data = await subscription_payload(
        session,
        services.store,
        user,
        base_url=await _public_base_url(session, services),
        token=token,
    )
    return {"token": token, **data}


@router.post("/users/{user_id}/subscription/rotate")
async def rotate_user_subscription(
    user_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    token = await rotate_subscription(session, services.store, user)
    await audit(
        session,
        actor=admin.username,
        action="user.subscription_rotated",
        target=user.name,
        ip=client_ip(request),
    )
    data = await subscription_payload(
        session,
        services.store,
        user,
        base_url=await _public_base_url(session, services),
        token=token,
    )
    return {"token": token, **data}


@router.get("/users/{user_id}/export")
async def export_user(
    user_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _get_user(session, user_id)
    endpoints = await endpoints_for_user(
        session, services.store, user, server_host=await server_hostname(session)
    )
    document = ProfileDocument(name=user.name, generated_at=iso(utcnow()), endpoints=endpoints)
    await audit(
        session,
        actor=admin.username,
        action="user.exported",
        target=user.name,
        ip=client_ip(request),
        detail={"endpoints": len(endpoints)},
    )
    return cast(dict[str, Any], json.loads(document.to_json()))


@router.post("/users/bulk")
async def bulk_users(
    payload: BulkRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    users = (
        (await session.execute(select(ProxyUser).where(ProxyUser.id.in_(payload.ids))))
        .scalars()
        .all()
    )
    if not users:
        raise ApiError(404, "no matching users", "not_found")
    touched: list[str] = []
    for user in users:
        touched.append(user.name)
        if payload.action == "enable":
            user.enabled = True
            user.disabled_reason = None
        elif payload.action == "disable":
            user.enabled = False
            user.disabled_reason = "disabled"
        elif payload.action == "delete":
            await session.delete(user)
        elif payload.action == "rotate":
            await rotate_credentials(session, services.store, user)
    if payload.action != "export":
        await session.flush()
        applied = await _apply_server(services, session)
        exports: list[dict[str, Any]] = []
    else:
        applied = {}
        exports = []
        for user in users:
            endpoints = await endpoints_for_user(
                session, services.store, user, server_host=await server_hostname(session)
            )
            exports.append(
                {
                    "user": user.name,
                    "profile": json.loads(
                        ProfileDocument(
                            name=user.name,
                            generated_at=iso(utcnow()),
                            endpoints=endpoints,
                        ).to_json()
                    ),
                }
            )
    await audit(
        session,
        actor=admin.username,
        action=f"user.bulk_{payload.action}",
        target=",".join(touched)[:255],
        ip=client_ip(request),
        detail={"count": len(touched)},
    )
    return {"count": len(touched), "action": payload.action, "exports": exports, **applied}


@router.get("/subscriptions")
async def subscriptions_overview(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    users = (
        (await session.execute(select(ProxyUser).order_by(ProxyUser.created_at))).scalars().all()
    )
    items = []
    for user in users:
        token = decrypt_subscription_token(user, services.store)
        items.append(
            {
                "user": serialize_user(user),
                "has_token": token is not None,
                "status": status_of(user),
                "links": (
                    [
                        endpoint.to_uri()
                        for endpoint in await build_endpoints(session, services.store, user)
                    ]
                    if status_of(user) in {"active", "online"}
                    else []
                ),
            }
        )
    return {"subscriptions": items, "base_url": await _public_base_url(session, services)}
