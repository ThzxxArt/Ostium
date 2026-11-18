"""Subscription URLs, user information headers and QR helpers."""

from __future__ import annotations

from datetime import UTC
from urllib.parse import urlsplit

import segno
from django.conf import settings
from django.db.models import Sum
from django.http import HttpRequest
from django.utils import timezone

from ostium.proxy.models import ProxyUser

TARGETS = {
    "base64": {
        "label": "Base64",
        "description": "v2rayN, v2rayNG, Shadowrocket and other V2Ray-style clients.",
        "suffix": "",
        "query": "",
    },
    "clash": {
        "label": "Clash / Mihomo",
        "description": "Clash Verge Rev, Mihomo Party and other Clash Meta clients.",
        "suffix": "/clash",
        "query": "?target=clash",
    },
    "singbox": {
        "label": "sing-box",
        "description": "The official sing-box client configuration.",
        "suffix": "/singbox",
        "query": "?target=singbox",
    },
    "uri": {
        "label": "Plain URI",
        "description": "One share link per line, for manual import and debugging.",
        "suffix": "",
        "query": "?target=uri",
    },
}


def public_host(request: HttpRequest | None = None) -> str:
    from constance import config

    configured = (config.public_host or "").strip()
    if configured:
        return configured.strip("[]")
    if settings.OSTIUM_PUBLIC_BASE_URL:
        hostname = urlsplit(settings.OSTIUM_PUBLIC_BASE_URL).hostname
        if hostname:
            return hostname
    if request is not None:
        host = request.get_host()
        return host.rsplit(":", 1)[0] if host.count(":") == 1 else host.strip("[]")
    return "localhost"


def public_base_url(request: HttpRequest | None = None) -> str:
    from constance import config

    configured = (config.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    if settings.OSTIUM_PUBLIC_BASE_URL:
        return settings.OSTIUM_PUBLIC_BASE_URL
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return "http://127.0.0.1:8000"


def subscription_url(user: ProxyUser, target: str, request: HttpRequest | None = None) -> str:
    token = user.reveal_subscription_token()
    base = f"{public_base_url(request)}/sub/{token}"
    spec = TARGETS[target]
    if target == "uri":
        return f"{base}?target=uri"
    return f"{base}{spec['suffix']}"


def subscription_links(user: ProxyUser, request: HttpRequest | None = None) -> list[dict]:
    links = []
    for target, spec in TARGETS.items():
        links.append(
            {
                "target": target,
                "label": spec["label"],
                "description": spec["description"],
                "url": subscription_url(user, target, request),
            }
        )
    return links


def masked_token(user: ProxyUser) -> str:
    token = user.reveal_subscription_token()
    return f"{token[:6]}…{token[-4:]}"


def qr_data_uri(value: str, *, scale: int = 5) -> str:
    return segno.make(value, error="m").svg_data_uri(scale=scale, border=2, dark="#0b1220", light="#ffffff")


def userinfo_header(user: ProxyUser) -> str:
    totals = user.traffic_daily.aggregate(up=Sum("uplink"), down=Sum("downlink"))
    upload = totals["up"] or 0
    download = totals["down"] or 0
    if upload + download == 0 and user.used_bytes:
        upload = user.used_bytes
    expire = 0
    if user.expires_at:
        expire = int(user.expires_at.astimezone(UTC).timestamp())
    return f"upload={upload}; download={download}; total={user.quota_bytes}; expire={expire}"


def profile_title(user: ProxyUser) -> str:
    from constance import config

    server_name = (config.server_name or "Ostium").replace("\n", " ").replace("\r", " ")
    return f"{user.name}@{server_name}"


def subscription_context(user: ProxyUser, request: HttpRequest | None = None) -> dict:
    return {
        "user": user,
        "token_masked": masked_token(user),
        "links": subscription_links(user, request),
        "qr": qr_data_uri(subscription_url(user, "base64", request)),
        "userinfo": userinfo_header(user),
    }


def normalize_target(value: str | None) -> str | None:
    if not value:
        return "base64"
    value = value.strip().lower()
    aliases = {
        "base64": "base64",
        "v2ray": "base64",
        "default": "base64",
        "uri": "uri",
        "plain": "uri",
        "clash": "clash",
        "clash-meta": "clash",
        "clash.meta": "clash",
        "mihomo": "clash",
        "singbox": "singbox",
        "sing-box": "singbox",
        "sing_box": "singbox",
    }
    return aliases.get(value)


__all__ = [
    "TARGETS",
    "masked_token",
    "normalize_target",
    "profile_title",
    "public_base_url",
    "public_host",
    "qr_data_uri",
    "subscription_context",
    "subscription_links",
    "subscription_url",
    "userinfo_header",
]


def now_utc():
    return timezone.now().astimezone(UTC)
