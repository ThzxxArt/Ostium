"""Audit trail, alerting and request metadata helpers."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from .models import Alert, AuditEvent

logger = logging.getLogger("ostium.operations")


def client_ip(request: HttpRequest) -> str | None:
    """Return the client address, trusting proxy headers only when configured."""

    if settings.OSTIUM_BEHIND_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[-1].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def record_audit(
    *,
    action: str,
    request: HttpRequest | None = None,
    actor: Any | None = None,
    target: str = "",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    if request is not None:
        if actor is None and getattr(request, "user", None) and request.user.is_authenticated:
            actor = request.user
        if actor is None and getattr(request, "api_key", None) is not None:
            actor = getattr(request.api_key, "created_by", None)
        ip = client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
    else:
        ip = None
        user_agent = ""
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target=target[:200],
        ip=ip,
        user_agent=user_agent,
        detail=detail or {},
    )


def raise_alert(
    *,
    code: str,
    message: str,
    level: str = Alert.Level.WARNING,
    fingerprint: str | None = None,
    detail: dict[str, Any] | None = None,
) -> Alert:
    key = fingerprint or code
    now = timezone.now()
    alert, created = Alert.objects.get_or_create(
        fingerprint=key,
        defaults={
            "code": code,
            "message": message,
            "level": level,
            "detail": detail or {},
            "first_seen_at": now,
            "last_seen_at": now,
        },
    )
    reopened = False
    if not created:
        updates = {
            "message": message,
            "level": level,
            "detail": detail or {},
            "last_seen_at": now,
        }
        # Acknowledging an active condition must survive the periodic
        # re-raise. Only an alert that was explicitly resolved may reopen.
        if alert.resolved_at is not None:
            updates["resolved_at"] = None
            updates["acknowledged_at"] = None
            reopened = True
        Alert.objects.filter(pk=alert.pk).update(**updates)
        alert.refresh_from_db()
    logger.warning("alert raised", extra={"code": code, "level": level})
    if created or reopened:
        from .webhook import notify_alert

        notify_alert(alert)
    return alert


def acknowledge_alert(alert: Alert) -> Alert:
    Alert.objects.filter(pk=alert.pk).update(acknowledged_at=timezone.now())
    alert.refresh_from_db()
    return alert


def cancel_queued_job(task_id: str) -> bool:
    """Remove a queued django-q2 message by its task id."""

    from django_q.models import OrmQ

    for queued in OrmQ.objects.all():
        try:
            if queued.task_id() == task_id:
                queued.delete()
                return True
        except Exception:  # noqa: S112 - one corrupt queue row must not block cancellation
            continue
    return False


def resolve_alert(fingerprint: str) -> None:
    now = timezone.now()
    Alert.objects.filter(fingerprint=fingerprint, resolved_at__isnull=True).update(
        acknowledged_at=now,
        resolved_at=now,
    )
