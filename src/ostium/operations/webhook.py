"""Signed alert webhooks with SSRF protection."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from django.utils import timezone

logger = logging.getLogger("ostium.webhook")

_TIMEOUT = 5.0
_MAX_ATTEMPTS = 3


class WebhookError(RuntimeError):
    pass


def _is_public_address(address: str) -> bool:
    try:
        value = ipaddress.ip_address(address)
    except ValueError:
        return False
    return value.is_global and not (
        value.is_private
        or value.is_loopback
        or value.is_link_local
        or value.is_multicast
        or value.is_reserved
        or value.is_unspecified
    )


def validate_webhook_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise WebhookError("Webhook URL must be an https:// URL with a host.")
    if parsed.username or parsed.password:
        raise WebhookError("Webhook URL must not contain credentials.")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public_address(str(literal)):
            raise WebhookError("Webhook URL must not target a private or reserved address.")
        return url
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebhookError(f"Webhook host could not be resolved: {exc}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise WebhookError("Webhook host resolves to a private or reserved address.")
    return url


def sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver_webhook(
    url: str,
    secret: str,
    payload: dict[str, Any],
    *,
    attempts: int = _MAX_ATTEMPTS,
    timeout: float = _TIMEOUT,
) -> bool:
    """Deliver one signed payload. Returns True after a 2xx response."""

    if not secret:
        raise WebhookError("Webhook secret is required.")
    validate_webhook_url(url)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Ostium-Server-Webhook/0.2",
        "X-Ostium-Signature": sign_payload(secret, body),
    }
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                response = client.post(url, content=body, headers=headers)
            if 200 <= response.status_code < 300:
                return True
            logger.warning("webhook returned HTTP %s", response.status_code)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("webhook delivery failed: %s", exc)
        if attempt < attempts:
            time.sleep(min(4, 2 ** (attempt - 1)))
    return False


def alert_payload(alert) -> dict[str, Any]:
    return {
        "id": alert.pk,
        "code": alert.code,
        "level": alert.level,
        "message": alert.message,
        "detail": alert.detail,
        "fingerprint": alert.fingerprint,
        "first_seen_at": alert.first_seen_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "sent_at": timezone.now().isoformat(),
    }


def notify_alert(alert, *, background: bool = True) -> None:
    """Send an alert webhook if configured. Never blocks the caller."""

    try:
        from constance import config

        url = (config.webhook_url or "").strip()
        secret = (config.webhook_secret or "").strip()
    except Exception:
        return
    if not url or not secret:
        return
    payload = alert_payload(alert)

    def run() -> None:
        try:
            deliver_webhook(url, secret, payload)
        except Exception:
            logger.exception("webhook delivery failed")

    if background:
        threading.Thread(target=run, name="ostium-webhook", daemon=True).start()
    else:
        run()


__all__ = [
    "WebhookError",
    "alert_payload",
    "deliver_webhook",
    "notify_alert",
    "sign_payload",
    "validate_webhook_url",
]
