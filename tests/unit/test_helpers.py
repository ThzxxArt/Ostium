"""Formatting, redaction and subscription URL helpers."""

from __future__ import annotations

import pytest

from ostium.formatting import format_bps, format_bytes, format_duration, short_hash
from ostium.redaction import redact
from ostium.subscriptions.services import (
    masked_token,
    public_host,
    subscription_links,
    userinfo_header,
)


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.0 KiB"
    assert format_bytes(1536) == "1.5 KiB"
    assert format_bytes(None) == "—"
    assert format_bps(2048) == "2.0 KiB/s"
    assert format_duration(65) == "1m 5s"
    assert format_duration(3660) == "1h 1m"
    assert format_duration(None) == "—"
    assert short_hash("abcdef0123456789", 6) == "abcdef"


def test_redact_secrets():
    text = (
        "Authorization: Api-Key abcdef\n"
        "vless://uuid@example.com:443?pbk=secret\n"
        "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"
        "token=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    cleaned = redact(text)
    assert "Api-Key abcdef" not in cleaned
    assert "vless://" not in cleaned
    assert "BEGIN PRIVATE KEY" not in cleaned
    assert "aaaaaaaaaaaaaaaa" not in cleaned


@pytest.mark.django_db
def test_subscription_helpers(proxy_user, settings):
    settings.OSTIUM_PUBLIC_BASE_URL = "https://vpn.example.com"
    links = subscription_links(proxy_user)
    assert {link["target"] for link in links} == {"base64", "clash", "singbox", "uri"}
    assert links[1]["url"].endswith("/clash")
    assert "https://vpn.example.com/sub/" in links[0]["url"]
    assert masked_token(proxy_user).endswith(proxy_user.reveal_subscription_token()[-4:])
    header = userinfo_header(proxy_user)
    assert "total=107374182400" in header
    assert "expire=0" in header


@pytest.mark.django_db
def test_public_host_fallbacks(settings):
    settings.OSTIUM_PUBLIC_BASE_URL = "https://vpn.example.com:8443"
    assert public_host(None) == "vpn.example.com"
    settings.OSTIUM_PUBLIC_BASE_URL = ""
    assert public_host(None) == "localhost"
