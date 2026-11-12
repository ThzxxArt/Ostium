"""Audit log endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import get_current_admin, get_session
from ostium.db.models import AdminUser
from ostium.services.audit import list_audit, serialize_audit

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def audit_log(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await list_audit(session, limit=limit, offset=offset)
    return {"entries": [serialize_audit(row) for row in rows], "limit": limit, "offset": offset}
