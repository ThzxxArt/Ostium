"""Client profile management and subscription import/refresh."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.config import Role
from ostium.db.models import AdminUser, Profile
from ostium.engine.manager import EngineError
from ostium.services.audit import audit
from ostium.services.profiles import (
    ProfileError,
    create_profile,
    endpoints_from_profile,
    parse_subscription_text,
    refresh_profile,
    serialize_profile,
    subscription_url_of,
)
from ostium.util.time import iso

router = APIRouter(tags=["profiles"])


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    text: str | None = None
    url: str | None = None


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    selected_endpoint: str | None = None
    sort_order: int | None = None


class ReorderProfiles(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class ImportRequest(BaseModel):
    name: str | None = None
    text: str | None = None
    url: str | None = None


def _require_client(services: Services) -> None:
    if services.settings.role is not Role.CLIENT:
        raise ApiError(400, "profiles are only available on the client role", "role_mismatch")


async def _get_profile(session: AsyncSession, profile_id: str) -> Profile:
    profile = await session.get(Profile, profile_id)
    if profile is None:
        raise ApiError(404, "profile not found", "not_found")
    return profile


async def _apply_client(services: Services, session: AsyncSession) -> dict[str, Any]:
    try:
        result = await services.engine.apply_client(session)
        return {"applied": True, "revision": result["status"].get("revision")}
    except EngineError as exc:
        if exc.code in {
            "core_unavailable",
            "core_unreachable",
            "engine_unavailable",
            "no_profile",
        }:
            return {"applied": False, "warning": str(exc)}
        raise ApiError(exc.status_code, str(exc), exc.code) from exc


@router.get("/profiles")
async def list_profiles(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profiles = (
        (await session.execute(select(Profile).order_by(Profile.sort_order, Profile.created_at)))
        .scalars()
        .all()
    )
    from ostium.services.settings import get_setting

    active_profile_id = await get_setting(session, "active_profile_id")
    payloads = []
    for profile in profiles:
        data = serialize_profile(profile, services.store)
        data["active"] = profile.id == active_profile_id
        payloads.append(data)
    return {"profiles": payloads, "active_profile_id": active_profile_id}


@router.post("/profiles", status_code=201)
async def add_profile(
    payload: ProfileCreate,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    text = payload.text
    subscription_url = payload.url
    if subscription_url:
        from ostium.services.netguard import UnsafeUrlError, validate_remote_url
        from ostium.services.profiles import MAX_SUBSCRIPTION_BYTES

        try:
            subscription_url = validate_remote_url(subscription_url, allow_private=True)
        except UnsafeUrlError as exc:
            raise ApiError(400, str(exc), "unsafe_url") from exc
    if subscription_url and not text:
        from ostium.services.netguard import UnsafeUrlError, fetch_limited

        try:
            fetched = await fetch_limited(
                subscription_url,
                allow_private=True,
                max_bytes=MAX_SUBSCRIPTION_BYTES,
                timeout=20.0,
                headers={"User-Agent": "Ostium/0.1"},
            )
        except UnsafeUrlError as exc:
            raise ApiError(400, str(exc), "unsafe_url") from exc
        except ValueError as exc:
            raise ApiError(400, str(exc), "too_large") from exc
        except httpx.HTTPError as exc:
            raise ApiError(502, f"subscription download failed: {exc}", "refresh_failed") from exc
        if fetched.status_code >= 400:
            raise ApiError(
                502,
                f"subscription download failed: HTTP {fetched.status_code}",
                "refresh_failed",
            )
        text = fetched.text
    if not text:
        raise ApiError(400, "either text or url is required", "bad_request")
    try:
        endpoints = parse_subscription_text(text)
        profile = await create_profile(
            session,
            services.store,
            name=payload.name,
            endpoints=endpoints,
            kind="subscription" if subscription_url else "manual",
            subscription_url=subscription_url,
        )
    except ProfileError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="profile.created",
        target=profile.name,
        ip=client_ip(request),
        detail={"endpoints": len(endpoints), "subscription": bool(subscription_url)},
    )
    return {"profile": serialize_profile(profile, services.store), **applied}


@router.post("/profiles/import")
async def import_profile(
    payload: ImportRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await add_profile(
        ProfileCreate(name=payload.name or "Imported", text=payload.text, url=payload.url),
        request,
        admin,
        services,
        session,
    )


@router.patch("/profiles/{profile_id}")
async def update_profile(
    profile_id: str,
    payload: ProfilePatch,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profile = await _get_profile(session, profile_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name"):
        profile.name = changes["name"]
    if "enabled" in changes and changes["enabled"] is not None:
        profile.enabled = changes["enabled"]
        if not profile.enabled:
            from ostium.services.settings import get_setting, set_setting

            if await get_setting(session, "active_profile_id") == profile.id:
                await set_setting(session, "active_profile_id", None)
    if "selected_endpoint" in changes:
        profile.selected_endpoint = changes["selected_endpoint"]
    if "sort_order" in changes and changes["sort_order"] is not None:
        profile.sort_order = changes["sort_order"]
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="profile.updated",
        target=profile.name,
        ip=client_ip(request),
        detail={"fields": sorted(changes)},
    )
    return {"profile": serialize_profile(profile, services.store), **applied}


@router.post("/profiles/reorder")
async def reorder_profiles(
    payload: ReorderProfiles,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profiles = (await session.execute(select(Profile))).scalars().all()
    by_id = {profile.id: profile for profile in profiles}
    if len(payload.ids) != len(set(payload.ids)) or set(payload.ids) != set(by_id):
        raise ApiError(422, "reorder must contain every profile exactly once", "invalid_reorder")
    for index, profile_id in enumerate(payload.ids):
        by_id[profile_id].sort_order = index * 10
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="profile.reordered",
        ip=client_ip(request),
        detail={"count": len(payload.ids)},
    )
    return {"ok": True, **applied}


@router.post("/profiles/{profile_id}/activate")
async def activate_profile(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profile = await _get_profile(session, profile_id)
    if not profile.enabled:
        raise ApiError(409, "enable the profile before activating it", "profile_disabled")
    from ostium.services.settings import set_setting

    await set_setting(session, "active_profile_id", profile.id)
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="profile.activated",
        target=profile.name,
        ip=client_ip(request),
    )
    data = serialize_profile(profile, services.store)
    data["active"] = True
    return {"profile": data, **applied}


@router.delete("/profiles/{profile_id}")
async def delete_profile(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profile = await _get_profile(session, profile_id)
    name = profile.name
    from ostium.services.settings import get_setting, set_setting

    if await get_setting(session, "active_profile_id") == profile.id:
        await set_setting(session, "active_profile_id", None)
    await session.delete(profile)
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session, actor=admin.username, action="profile.deleted", target=name, ip=client_ip(request)
    )
    return {"deleted": True, **applied}


@router.post("/profiles/{profile_id}/refresh")
async def refresh(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profile = await _get_profile(session, profile_id)
    try:
        count = await refresh_profile(session, services.store, profile)
    except ProfileError as exc:
        # ``refresh_profile`` records last_refresh_error before raising.  The
        # request-level session would roll that flush back when the API error
        # propagates, so persist the diagnostic explicitly.
        await session.commit()
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="profile.refreshed",
        target=profile.name,
        ip=client_ip(request),
        detail={"endpoints": count},
    )
    return {"profile": serialize_profile(profile, services.store), "endpoints": count, **applied}


@router.get("/profiles/{profile_id}/export")
async def export_profile(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    profile = await _get_profile(session, profile_id)
    endpoints = endpoints_from_profile(profile, services.store)
    await audit(
        session,
        actor=admin.username,
        action="profile.exported",
        target=profile.name,
        ip=client_ip(request),
        detail={"endpoints": len(endpoints)},
    )
    return {
        "name": profile.name,
        "subscription_url": subscription_url_of(profile, services.store),
        "endpoints": [endpoint.model_dump(mode="json") for endpoint in endpoints],
        "last_refresh_at": iso(profile.last_refresh_at),
    }


@router.get("/profiles/{profile_id}/test")
async def test_profile(
    profile_id: str,
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_client(services)
    profile = await _get_profile(session, profile_id)
    endpoints = endpoints_from_profile(profile, services.store)
    proxies = (await services.clash.proxies()).get("proxies", {})
    import asyncio

    async def measure(endpoint: Any) -> dict[str, Any]:
        item: dict[str, Any] = {
            "tag": endpoint.tag,
            "name": endpoint.name,
            "delay_ms": None,
            "error": None,
        }
        if endpoint.tag not in proxies:
            item["error"] = "not loaded in the running core; apply the profile first"
            return item
        delay = await services.clash.delay(endpoint.tag, url="https://www.gstatic.com/generate_204")
        if delay is None:
            item["error"] = "latency probe failed or timed out"
        else:
            item["delay_ms"] = delay
        return item

    results = await asyncio.gather(*(measure(endpoint) for endpoint in endpoints))
    return {"profile": profile.name, "results": results}
