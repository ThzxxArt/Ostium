"""Audit log, alerts and webhook delivery."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.db.models import Alert, AuditLog
from ostium.services.events import EventBus
from ostium.util.redact import redact, redact_mapping
from ostium.util.time import iso, utcnow


async def audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    target: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor[:100],
        action=action[:100],
        target=(target or "")[:255] or None,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:255] or None,
        detail_json=redact_mapping(detail or {}),
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_audit(session: AsyncSession, limit: int = 200, offset: int = 0) -> list[AuditLog]:
    return list(
        (
            await session.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )


def serialize_audit(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor": entry.actor,
        "action": entry.action,
        "target": entry.target,
        "ip": entry.ip,
        "detail": entry.detail_json,
        "created_at": iso(entry.created_at),
    }


async def create_alert(
    session: AsyncSession,
    bus: EventBus,
    *,
    level: str,
    code: str,
    message: str,
    dedupe_key: str | None = None,
) -> Alert:
    from ostium.services.settings import get_setting

    text = redact(message)[:500]
    effective_code = code
    if dedupe_key:
        import hashlib

        effective_code = f"{code}:{hashlib.sha256(dedupe_key.encode()).hexdigest()[:10]}"
    existing = (
        await session.execute(
            select(Alert)
            .where(Alert.code == effective_code, Alert.acknowledged_at.is_(None))
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.level = level
        existing.message = text
        existing.created_at = utcnow()
        await session.flush()
        await bus.publish(
            "alert.updated",
            {
                "id": existing.id,
                "level": level,
                "code": effective_code,
                "message": text,
            },
        )
        return existing
    alert = Alert(level=level, code=effective_code, message=text)
    session.add(alert)
    await session.flush()
    await bus.publish(
        "alert.created",
        {"id": alert.id, "level": level, "code": code, "message": alert.message},
    )
    webhook_url = await get_setting(session, "webhook_url")
    notifications_enabled = bool(await get_setting(session, "notifications_enabled", True))
    if webhook_url and notifications_enabled:
        secret = await get_setting(session, "webhook_secret", "")
        payload = {"type": "alert", "level": level, "code": code, "message": alert.message}

        async def _deliver() -> None:
            delivered = await send_webhook(str(webhook_url), payload, str(secret or ""))
            if not delivered:
                bus.log("warning", "webhook delivery failed", code=code)

        asyncio.create_task(_deliver())
    return alert


async def list_alerts(session: AsyncSession, include_acknowledged: bool = False) -> list[Alert]:
    query = select(Alert).order_by(Alert.created_at.desc()).limit(100)
    if not include_acknowledged:
        query = query.where(Alert.acknowledged_at.is_(None))
    return list((await session.execute(query)).scalars().all())


async def acknowledge(session: AsyncSession, alert_id: str) -> bool:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        return False
    alert.acknowledged_at = utcnow()
    await session.flush()
    return True


def serialize_alert(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "level": alert.level,
        "code": alert.code,
        "message": alert.message,
        "acknowledged_at": iso(alert.acknowledged_at),
        "created_at": iso(alert.created_at),
    }


async def send_webhook(url: str, payload: dict[str, Any], secret: str = "") -> bool:
    import hashlib
    import hmac
    import json

    from ostium.services.netguard import UnsafeUrlError, validate_remote_url

    try:
        url = validate_remote_url(url, allow_private=False)
    except UnsafeUrlError:
        return False
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "Ostium/0.1"}
    if secret:
        headers["X-Ostium-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.post(url, content=body, headers=headers)
            if response.status_code < 300:
                return True
            if response.status_code < 500:
                return False
        except httpx.HTTPError:
            pass
        if attempt < 2:
            await asyncio.sleep(2**attempt)
    return False
