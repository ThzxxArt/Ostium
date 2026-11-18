"""Validation shared by the API, console and settings forms."""

from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings

SECRET_SETTINGS = frozenset({"webhook_secret"})
MASKED_SECRET = "*" * 8


class SettingValidationError(ValueError):
    pass


def _as_bool(key: str, value) -> bool:
    if isinstance(value, bool):
        return value
    raise SettingValidationError(f"{key} must be a boolean.")


def _as_int(key: str, value) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise SettingValidationError(f"{key} must be an integer.") from exc
    if converted < 0:
        raise SettingValidationError(f"{key} must not be negative.")
    return converted


def _as_text(key: str, value) -> str:
    if not isinstance(value, str):
        raise SettingValidationError(f"{key} must be a string.")
    if any(ord(char) < 32 and char not in "\t" for char in value):
        raise SettingValidationError(f"{key} must not contain control characters.")
    return value.strip()


def _https_url(key: str, value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SettingValidationError(f"{key} must be an https:// URL without credentials.")
    return value.rstrip("/")


def _public_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SettingValidationError("public_base_url must be an absolute http(s) URL.")
    if parsed.username or parsed.password:
        raise SettingValidationError("public_base_url must not contain credentials.")
    return value.rstrip("/")


def _public_host(value: str) -> str:
    if not value:
        return ""
    if "://" in value or "/" in value or any(char.isspace() for char in value):
        raise SettingValidationError("public_host must be a bare hostname or IP address.")
    # A single colon is a port, which would be appended again to every
    # subscription endpoint. Multiple colons are an IPv6 literal.
    if value.count(":") == 1 and not value.startswith("["):
        raise SettingValidationError("public_host must not include a port.")
    return value.strip("[]")


def coerce_setting(key: str, value):
    """Validate and normalize one runtime setting."""

    definition = settings.CONSTANCE_CONFIG.get(key)
    if definition is None:
        raise SettingValidationError(f"Unknown setting: {key}")
    default = definition[0]

    if isinstance(default, bool):
        return _as_bool(key, value)
    if isinstance(default, int):
        converted = _as_int(key, value)
        limits = {
            "subscription_update_interval": (1, 720),
            "traffic_retention_days": (1, 3650),
            "audit_retention_days": (1, 3650),
            "auto_backup_keep": (1, 100),
        }
        if key in limits:
            low, high = limits[key]
            if not low <= converted <= high:
                raise SettingValidationError(f"{key} must be between {low} and {high}.")
        return converted

    text = _as_text(key, value)
    if key == "server_name":
        if not text or len(text) > 100:
            raise SettingValidationError("server_name must be between 1 and 100 characters.")
    elif key == "server_dns_mode":
        if text not in {"auto", "doh", "udp"}:
            raise SettingValidationError("server_dns_mode must be auto, doh or udp.")
    elif key == "log_level":
        if text not in {"trace", "debug", "info", "warn", "error"}:
            raise SettingValidationError("log_level must be trace, debug, info, warn or error.")
    elif key in {"server_dns_doh_url", "webhook_url"}:
        if text:
            text = _https_url(key, text)
    elif key == "public_base_url":
        if text:
            text = _public_base_url(text)
    elif key == "public_host":
        text = _public_host(text)
    elif key == "webhook_secret" and len(text) > 256:
        raise SettingValidationError("webhook_secret must be at most 256 characters.")
    return text


__all__ = [
    "MASKED_SECRET",
    "SECRET_SETTINGS",
    "SettingValidationError",
    "coerce_setting",
]
