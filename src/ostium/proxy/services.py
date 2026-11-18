"""Domain services for proxy users and inbounds."""

from __future__ import annotations

import re
from datetime import datetime

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from ostium.operations.models import RuntimeState
from ostium.operations.services import raise_alert

from .models import Inbound, ProxyUser, StatsEpoch, TrafficDaily

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgtp]?i?b?)?\s*$", re.IGNORECASE)
_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "ki": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mi": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gi": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "ti": 1024**4,
    "tib": 1024**4,
    "p": 1024**5,
    "pb": 1024**5,
    "pib": 1024**5,
}


def parse_size(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return max(0, value)
    match = _SIZE_RE.match(value)
    if not match:
        raise ValueError(f"Invalid size: {value!r}")
    number, unit = match.groups()
    return int(float(number) * _UNITS[unit.lower()])


def mark_dirty() -> int:
    return RuntimeState.mark_desired()


@transaction.atomic
def create_proxy_user(
    name: str,
    *,
    quota_bytes: int = 0,
    quota_cycle: str = ProxyUser.QuotaCycle.TOTAL,
    expires_at: datetime | None = None,
    note: str = "",
    enabled: bool = True,
) -> tuple[ProxyUser, str]:
    user = ProxyUser(
        name=name.strip(),
        quota_bytes=quota_bytes,
        quota_cycle=quota_cycle,
        expires_at=expires_at,
        note=note,
        enabled=enabled,
    )
    # Populate encrypted fields before the first save; the UUID primary key is
    # generated in the model constructor, which is required for AAD binding.
    user.set_password()
    user.set_ss_password()
    token = user.set_subscription_token()
    user.cycle_started_at = timezone.now()
    user.save()
    StatsEpoch.objects.get_or_create(user=user, active=True)
    return user, token


def active_queryset() -> QuerySet[ProxyUser]:
    now = timezone.now()
    return ProxyUser.objects.filter(enabled=True).filter(models_q_expired(now)).filter(models_q_quota())


def models_q_expired(now: datetime):
    from django.db.models import Q

    return Q(expires_at__isnull=True) | Q(expires_at__gt=now)


def models_q_quota():
    from django.db.models import Q

    return Q(quota_bytes=0) | Q(used_bytes__lt=F("quota_bytes"))


def config_queryset() -> QuerySet[ProxyUser]:
    return active_queryset().order_by("name")


def enabled_inbounds() -> QuerySet[Inbound]:
    return Inbound.objects.filter(enabled=True).select_related("certificate").order_by("kind")


def initialize_inbounds(*, enable: tuple[str, ...] = ()) -> list[Inbound]:
    """Create the four protocol records with generated secrets."""

    records: list[Inbound] = []
    for kind in Inbound.Kind:
        record, created = Inbound.objects.get_or_create(
            kind=kind,
            defaults={
                "port": Inbound.DEFAULT_PORTS[kind],
                "enabled": kind in enable,
            },
        )
        if created:
            record.ensure_defaults()
            record.save()
        records.append(record)
    return records


def account_usage(user: ProxyUser, since_days: int = 30) -> list[dict]:
    rows = TrafficDaily.objects.filter(user=user).order_by("-day")[:since_days].values("day", "uplink", "downlink")
    return list(rows)


def enforce_limits(now: datetime | None = None) -> bool:
    """Apply expiry, monthly rollover and quota state. Returns True if config changed."""

    now = now or timezone.now()
    changed = False
    for user in ProxyUser.objects.all().iterator():
        if user.roll_month_if_needed(now):
            changed = True
        if not user.enabled:
            continue
        if user.is_expired:
            user.disable(ProxyUser.DisabledReason.EXPIRED)
            changed = True
            continue
        if user.is_over_quota:
            user.disable(ProxyUser.DisabledReason.QUOTA_EXCEEDED)
            changed = True
            continue
        percent = user.quota_percent
        if percent is not None and user.quota_bytes > 0:
            ratio = user.used_bytes / user.quota_bytes
            for threshold in (0.8, 0.9):
                if ratio >= threshold:
                    raise_alert(
                        code=f"quota_{int(threshold * 100)}",
                        fingerprint=f"quota:{user.pk}:{int(threshold * 100)}",
                        level="warning" if threshold < 0.9 else "critical",
                        message=f"{user.name} has used {percent:.0f}% of the quota.",
                        detail={"user": str(user.pk)},
                    )
    if changed:
        mark_dirty()
    return changed


__all__ = [
    "account_usage",
    "active_queryset",
    "config_queryset",
    "create_proxy_user",
    "enabled_inbounds",
    "enforce_limits",
    "mark_dirty",
    "parse_size",
]
