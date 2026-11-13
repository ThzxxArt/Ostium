"""Job centre endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import (
    Services,
    client_ip,
    get_current_admin,
    get_services,
    get_session,
)
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, Job
from ostium.services.audit import audit
from ostium.services.jobs import list_jobs, serialize_job

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def jobs(
    limit: int = 100,
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await list_jobs(session, limit=max(1, min(limit, 500)))
    return {"jobs": [serialize_job(row) for row in rows]}


@router.get("/jobs/{job_id}")
async def job_detail(
    job_id: str,
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(Job, job_id)
    if row is None:
        raise ApiError(404, "job not found", "not_found")
    return {"job": serialize_job(row)}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(Job, job_id)
    if row is None:
        raise ApiError(404, "job not found", "not_found")
    ok = await services.jobs.cancel(job_id)
    if ok:
        await audit(
            session,
            actor=admin.username,
            action="job.cancelled",
            target=job_id,
            ip=client_ip(request),
        )
    return {"cancelled": ok}
