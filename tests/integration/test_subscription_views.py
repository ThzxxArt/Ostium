"""Subscription HTTP endpoint tests."""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from ostium.proxy.models import ProxyUser


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


def url(user: ProxyUser, suffix: str = "") -> str:
    return f"/sub/{user.reveal_subscription_token()}{suffix}"


@pytest.mark.django_db
def test_default_base64(client, proxy_user, vless_inbound):
    response = client.get(url(proxy_user))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert "Subscription-Userinfo" in response
    assert "Profile-Update-Interval" in response
    decoded = base64.b64decode(response.content).decode()
    assert decoded.startswith("vless://")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("suffix", "content_type"),
    [
        ("?target=uri", "text/plain"),
        ("?target=clash", "text/yaml"),
        ("?target=singbox", "application/json"),
        ("/clash", "text/yaml"),
        ("/singbox", "application/json"),
        ("/v2ray", "text/plain"),
    ],
)
def test_targets(client, proxy_user, vless_inbound, suffix, content_type):
    response = client.get(url(proxy_user, suffix))
    assert response.status_code == 200
    assert response["Content-Type"].startswith(content_type)


@pytest.mark.django_db
def test_profiles_do_not_override_client_dns(client, proxy_user, vless_inbound):
    import json

    import yaml

    clash = yaml.safe_load(client.get(url(proxy_user, "/clash")).content)
    assert "dns" not in clash
    assert "mixed-port" not in clash
    assert all(not rule.startswith("GEOIP,") for rule in clash["rules"])
    singbox = json.loads(client.get(url(proxy_user, "/singbox")).content)
    assert "dns" not in singbox
    assert "default_domain_resolver" not in singbox["route"]


@pytest.mark.django_db
def test_unknown_target(client, proxy_user, vless_inbound):
    assert client.get(url(proxy_user, "?target=nope")).status_code == 400


@pytest.mark.django_db
def test_unknown_token(client):
    assert client.get("/sub/" + "a" * 43).status_code == 404
    assert client.get("/sub/short").status_code == 404


@pytest.mark.django_db
def test_disabled_user(client, proxy_user, vless_inbound):
    proxy_user.enabled = False
    proxy_user.save(update_fields=["enabled"])
    assert client.get(url(proxy_user)).status_code == 403


@pytest.mark.django_db
def test_expired_user(client, proxy_user, vless_inbound):
    proxy_user.expires_at = timezone.now() - timedelta(seconds=1)
    proxy_user.save(update_fields=["expires_at"])
    assert client.get(url(proxy_user)).status_code == 403


@pytest.mark.django_db
def test_quota_exceeded(client, proxy_user, vless_inbound):
    proxy_user.used_bytes = proxy_user.quota_bytes
    proxy_user.save(update_fields=["used_bytes"])
    assert client.get(url(proxy_user)).status_code == 403


@pytest.mark.django_db
def test_no_enabled_inbounds(client, proxy_user, inbounds):
    for inbound in inbounds:
        inbound.enabled = False
        inbound.save(update_fields=["enabled"])
    assert client.get(url(proxy_user)).status_code == 403


@pytest.mark.django_db
def test_head_request(client, proxy_user, vless_inbound):
    response = client.head(url(proxy_user))
    assert response.status_code == 200
    assert response.content == b""
