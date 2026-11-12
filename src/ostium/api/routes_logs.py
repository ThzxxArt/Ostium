"""Control-plane and core log access."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from ostium.api.deps import Services, get_current_admin, get_services
from ostium.db.models import AdminUser
from ostium.engine.core_api import CoreApiError

router = APIRouter(tags=["logs"])


@router.get("/logs")
async def logs(
    source: str = Query(default="ostium", pattern="^(ostium|core)$"),
    level: str | None = None,
    search: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    if source == "core":
        try:
            text = await services.engine.client.logs(limit)
        except CoreApiError as exc:
            return {"source": "core", "lines": [], "error": exc.detail, "unavailable": True}
        lines = text.splitlines()[-limit:]
        if search:
            lines = [line for line in lines if search.lower() in line.lower()]
        return {"source": "core", "lines": lines, "unavailable": False}
    records = services.bus.logs(level=level, search=search, limit=limit)
    return {"source": "ostium", "records": records, "lines": [r["message"] for r in records]}


@router.get("/logs/download")
async def download_logs(
    source: str = Query(default="ostium", pattern="^(ostium|core)$"),
    _: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
) -> PlainTextResponse:
    if source == "core":
        try:
            content = await services.engine.client.logs(5000)
        except CoreApiError as exc:
            content = f"core logs unavailable: {exc.detail}\n"
    else:
        content = services.bus.export_logs()
    return PlainTextResponse(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ostium-{source}-logs.txt"'},
    )
