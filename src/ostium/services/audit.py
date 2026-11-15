"""Audit log, alerts and webhook delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.db.models import Alert, AuditLog
from ostium.services.events import EventBus
from ostium.util.redact import redact, redact_mapping
from ostium.util.time import iso, utcnow

# Set by the application after the SecretStore is available.  Keeping this in
# the service module avoids threading a store through every create_alert call
# site while still allowing webhook secrets to be encrypted at rest.
_SECRET_DECRYPTER: Any = None

# asyncio keeps only a weak reference to a running task.  Fire-and-forget
# webhook deliveries must hold a strong reference until they finish, otherwise
# a GC pass can cancel a delivery mid-flight.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_task)


def _discard_task(task: asyncio.Task[None]) -> None:
    _BACKGROUND_TASKS.discard(task)
    if not task.cancelled():
        # Retrieve the exception so a failed delivery cannot surface as an
        # "exception was never retrieved" warning at shutdown.
        task.exception()


def set_webhook_secret_decrypter(decrypter: Any) -> None:
    global _SECRET_DECRYPTER
    _SECRET_DECRYPTER = decrypter


async def _webhook_secret(session: AsyncSession) -> str:
    from ostium.services.settings import get_setting

    value = await get_setting(session, "webhook_secret", "")
    if not isinstance(value, str) or not value:
        return ""
    if not value.startswith("v1."):
        # Backward compatibility for secrets written before 0.1.2.
        return value
    if _SECRET_DECRYPTER is None:
        raise ValueError("webhook secret is encrypted but no decrypter is configured")
    return str(_SECRET_DECRYPTER(value))


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
        try:
            secret = await _webhook_secret(session)
        except Exception as exc:
            bus.log("error", "webhook secret could not be decrypted", error=str(exc))
            secret = ""
        payload = {"type": "alert", "level": level, "code": code, "message": alert.message}

        async def _deliver() -> None:
            delivered = await send_webhook(str(webhook_url), payload, str(secret or ""))
            if not delivered:
                bus.log("warning", "webhook delivery failed", code=code)

        _spawn(_deliver())
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

    from ostium.services.netguard import UnsafeUrlError, post_limited

    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "Ostium/0.1"}
    if secret:
        headers["X-Ostium-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    for attempt in range(3):
        try:
            status = await post_limited(url, content=body, headers=headers, timeout=10.0)
            if status < 300:
                return True
            if status < 500:
                return False
        except (httpx.HTTPError, UnsafeUrlError, ValueError):
            pass
        if attempt < 2:
            await asyncio.sleep(2**attempt)
    return False
