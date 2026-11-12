"""Backup listing, creation, restore staging and deletion."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, Backup
from ostium.services import backup as backup_service
from ostium.services.audit import audit
from ostium.services.jobs import JobContext
from ostium.util.time import iso

router = APIRouter(tags=["backups"])


class BackupRequest(BaseModel):
    password: str | None = None


class RestoreRequest(BaseModel):
    password: str | None = None


@router.get("/backups")
async def list_backups(
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (
        (await session.execute(select(Backup).order_by(Backup.created_at.desc()))).scalars().all()
    )
    files = {path.name for path in services.settings.paths.backups_dir.glob("ostium-backup-*")}
    return {
        "backups": [
            {
                "id": row.id,
                "filename": row.filename,
                "size": row.size,
                "sha256": row.sha256,
                "encrypted": row.encrypted,
                "created_at": iso(row.created_at),
                "exists": row.filename in files,
            }
            for row in rows
        ]
    }


@router.post("/backups", status_code=202)
async def create_backup(
    payload: BackupRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if payload.password is not None and len(payload.password) < 8:
        raise ApiError(400, "backup password must be at least 8 characters", "weak_password")

    async def job(context: JobContext) -> dict[str, Any]:
        await context.progress(20, "snapshotting database")
        result = backup_service.create_backup(
            services.settings, password=payload.password, include_master_key=True
        )
        await context.progress(85, "recording backup")
        async with services.session_factory() as job_session:
            job_session.add(
                Backup(
                    filename=result["filename"],
                    size=result["size"],
                    sha256=result["sha256"],
                    encrypted=result["encrypted"],
                )
            )
            await job_session.commit()
        return result

    row = await services.jobs.submit(
        "backup.create", job, message="create backup" + (" (encrypted)" if payload.password else "")
    )
    await audit(
        session,
        actor=admin.username,
        action="backup.requested",
        ip=client_ip(request),
        detail={"job_id": row.id, "encrypted": bool(payload.password)},
    )
    return {"job_id": row.id, "status": "queued"}


@router.post("/backups/{backup_id}/restore", status_code=202)
async def restore_backup(
    backup_id: str,
    payload: RestoreRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(Backup, backup_id)
    if row is None:
        raise ApiError(404, "backup not found", "not_found")
    source = services.settings.paths.backups_dir / row.filename
    if not source.is_file():
        raise ApiError(404, "backup file is missing", "not_found")
    try:
        staged = backup_service.stage_restore(services.settings, source, password=payload.password)
    except backup_service.BackupError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    await audit(
        session,
        actor=admin.username,
        action="backup.restore_staged",
        target=row.filename,
        ip=client_ip(request),
    )
    return {
        **staged,
        "restart_required": True,
        "message": (
            "Backup staged. Restart both Ostium services to apply it; "
            "the current data is untouched until then."
        ),
    }


@router.delete("/backups/{backup_id}")
async def delete_backup(
    backup_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(Backup, backup_id)
    if row is None:
        raise ApiError(404, "backup not found", "not_found")
    path = services.settings.paths.backups_dir / row.filename
    path.unlink(missing_ok=True)
    await session.delete(row)
    await audit(
        session,
        actor=admin.username,
        action="backup.deleted",
        target=row.filename,
        ip=client_ip(request),
    )
    return {"deleted": True}


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
