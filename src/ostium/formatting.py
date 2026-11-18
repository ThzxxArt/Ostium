"""Human-readable formatting helpers."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone


def format_bytes(value: int | float | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value <= 0:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.{decimals}f} {units[index]}"


def format_bps(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{format_bytes(value)}/s"


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%Y-%m-%d %H:%M")


def relative_time(value: datetime | None) -> str:
    if value is None:
        return "never"
    delta = timezone.now() - value
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def short_hash(value: str | None, length: int = 12) -> str:
    if not value:
        return "—"
    return value[:length]
