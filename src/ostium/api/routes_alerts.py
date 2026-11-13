"""Alerts endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import client_ip, get_current_admin, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser
from ostium.services.audit import acknowledge, audit, list_alerts, serialize_alert

router = APIRouter(tags=["alerts"])


@router.get("/alerts")
async def alerts(
    include_acknowledged: bool = Query(default=False),
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await list_alerts(session, include_acknowledged=include_acknowledged)
    return {"alerts": [serialize_alert(row) for row in rows]}


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    if not await acknowledge(session, alert_id):
        raise ApiError(404, "alert not found", "not_found")
    await audit(
        session,
        actor=admin.username,
        action="alert.acknowledged",
        target=alert_id,
        ip=client_ip(request),
    )
    return {"acknowledged": True}
