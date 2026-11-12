"""Statistics, live connections and engine metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, ProxyUser, TrafficDaily
from ostium.services.stats import usage_series
from ostium.util.time import iso, utcnow

router = APIRouter(tags=["stats"])


@router.get("/stats/overview")
async def overview(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    users = (await session.execute(select(ProxyUser))).scalars().all()
    today = utcnow().date()
    rows = (
        (await session.execute(select(TrafficDaily).where(TrafficDaily.day == today)))
        .scalars()
        .all()
    )
    today_up = sum(row.uplink for row in rows)
    today_down = sum(row.downlink for row in rows)
    snapshot = services.stats.snapshot() if services.stats is not None else {}
    engine_status: dict[str, Any] = {}
    try:
        engine_status = await services.engine.client.status()
    except Exception:
        engine_status = {"running": False, "last_error": "core service is unreachable"}
    connections = await services.clash.connections()
    return {
        "role": services.settings.role.value,
        "users": {
            "total": len(users),
            "enabled": sum(1 for user in users if user.enabled),
            "online": snapshot.get("online", 0) if snapshot else 0,
            "disabled": sum(1 for user in users if not user.enabled),
        },
        "traffic": {
            "today_up": today_up,
            "today_down": today_down,
            "session_up": connections.get("uploadTotal", 0),
            "session_down": connections.get("downloadTotal", 0),
        },
        "rates": {
            "up": snapshot.get("rate_up", 0.0) if snapshot else 0.0,
            "down": snapshot.get("rate_down", 0.0) if snapshot else 0.0,
        },
        "engine": {
            "running": engine_status.get("running", False),
            "revision": engine_status.get("revision"),
            "engine_version": engine_status.get("engine_version"),
            "last_error": engine_status.get("last_error"),
            "started_at": engine_status.get("started_at"),
        },
        "connections": len(connections.get("connections", [])),
        "online_users": snapshot.get("users", []) if snapshot else [],
        "generated_at": iso(utcnow()),
    }


@router.get("/stats/traffic")
async def traffic(
    days: int = Query(default=30, ge=1, le=365),
    user_id: str | None = None,
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    series = await usage_series(session, days=days, user_id=user_id)
    return {"series": series, "days": days, "user_id": user_id}


@router.get("/connections")
async def connections(
    search: str | None = None,
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    data = await services.clash.connections()
    items = data.get("connections", [])
    if search:
        needle = search.lower()
        items = [
            item
            for item in items
            if needle in str(item.get("metadata", {}).get("host", "")).lower()
            or needle in str(item.get("metadata", {}).get("destinationIP", "")).lower()
            or needle in str(item.get("metadata", {}).get("processPath", "")).lower()
        ]
    return {
        "connections": items,
        "upload_total": data.get("uploadTotal", 0),
        "download_total": data.get("downloadTotal", 0),
        "unavailable": data.get("unavailable", False),
    }


@router.delete("/connections/{connection_id}")
async def close_connection(
    connection_id: str,
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, bool]:
    ok = await services.clash.close_connection(connection_id)
    if not ok:
        raise ApiError(404, "connection not found or core unavailable", "not_found")
    return {"closed": True}


@router.delete("/connections")
async def close_all_connections(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, bool]:
    return {"closed": await services.clash.close_all()}


@router.get("/stats/engine")
async def engine_stats(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        status = await services.engine.client.status()
    except Exception as exc:
        return {"running": False, "error": str(exc)}
    return {"running": status.get("running", False), "status": status}


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> Any:
    from fastapi.responses import PlainTextResponse

    users = (await session.execute(select(func.count(ProxyUser.id)))).scalar_one()
    enabled = (
        await session.execute(select(func.count(ProxyUser.id)).where(ProxyUser.enabled.is_(True)))
    ).scalar_one()
    snapshot = services.stats.snapshot() if services.stats is not None else {}
    try:
        status = await services.engine.client.status()
        running = 1 if status.get("running") else 0
    except Exception:
        running = 0
    lines = [
        "# HELP ostium_users_total Number of proxy users",
        "# TYPE ostium_users_total gauge",
        f"ostium_users_total {users}",
        f"ostium_users_enabled {enabled}",
        f"ostium_engine_running {running}",
        "ostium_users_online {}".format(snapshot.get("online", 0) if snapshot else 0),
        "ostium_traffic_rate_up_bytes {}".format(snapshot.get("rate_up", 0.0) if snapshot else 0.0),
        "ostium_traffic_rate_down_bytes {}".format(
            snapshot.get("rate_down", 0.0) if snapshot else 0.0
        ),
    ]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
