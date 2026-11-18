"""Regression tests for the 0.2.0 acceptance review."""

from __future__ import annotations

import base64
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.test import RequestFactory
from django_otp.plugins.otp_totp.models import TOTPDevice

from ostium.engine.stats import StatsSampler
from ostium.operations.backup import _reencrypt_with_field_key
from ostium.operations.webhook import (
    WebhookError,
    deliver_webhook,
    sign_payload,
    validate_webhook_url,
)
from ostium.proxy.models import Inbound, ProxyUser, TrafficDaily
from ostium.proxy.services import create_proxy_user, enforce_limits
from ostium.redaction import redact
from ostium.subscriptions.services import public_host, userinfo_header


@pytest.mark.django_db
def test_flush_failure_keeps_pending_and_does_not_inflate_totals(proxy_user, monkeypatch):
    other, _ = create_proxy_user("bob")
    sampler = StatsSampler(pending={proxy_user.name: [11, 22], other.name: [33, 44]})
    original = TrafficDaily.objects.get_or_create
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("database unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(TrafficDaily.objects, "get_or_create", flaky)
    with pytest.raises(RuntimeError):
        sampler.flush()
    assert sampler.pending == {proxy_user.name: [11, 22], other.name: [33, 44]}
    assert sampler.total_uplink == 0
    assert sampler.total_downlink == 0
    proxy_user.refresh_from_db()
    assert proxy_user.used_bytes == 0


@pytest.mark.django_db
def test_enforce_limits_counts_pending_bytes(proxy_user):
    proxy_user.quota_bytes = 100
    proxy_user.used_bytes = 0
    proxy_user.save(update_fields=["quota_bytes", "used_bytes"])
    assert enforce_limits(pending={proxy_user.name: [100, 0]}) is True
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is False
    assert proxy_user.disabled_reason == ProxyUser.DisabledReason.QUOTA_EXCEEDED


@pytest.mark.django_db
def test_reset_usage_reenables_quota_suspended_user(proxy_user):
    proxy_user.quota_bytes = 10
    proxy_user.used_bytes = 10
    proxy_user.disable(ProxyUser.DisabledReason.QUOTA_EXCEEDED)
    proxy_user.reset_usage()
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is True
    assert proxy_user.disabled_reason == ""
    assert proxy_user.used_bytes == 0


@pytest.mark.django_db
def test_userinfo_uses_authoritative_counters(proxy_user):
    proxy_user.used_bytes = 0
    proxy_user.uploaded_bytes = 0
    proxy_user.downloaded_bytes = 0
    proxy_user.save(update_fields=["used_bytes", "uploaded_bytes", "downloaded_bytes"])
    TrafficDaily.objects.create(user=proxy_user, day=date.today() - timedelta(days=80), uplink=10**9)
    assert "upload=0; download=0" in userinfo_header(proxy_user)
    proxy_user.uploaded_bytes = 12
    proxy_user.downloaded_bytes = 34
    proxy_user.save(update_fields=["uploaded_bytes", "downloaded_bytes"])
    assert "upload=12; download=34" in userinfo_header(proxy_user)


def test_redact_json_secret_fields():
    text = '{"password":"AAAAAAAAAAAAAAAAAAAAAAAA","server_key":"BBBBBBBBBBBBBBBBBBBBBBBB"}'
    result = redact(text)
    assert "AAAAAAAAAAAAAAAAAAAAAAAA" not in result
    assert "BBBBBBBBBBBBBBBBBBBBBBBB" not in result


@pytest.mark.django_db
def test_public_host_ipv6_with_port():
    request = RequestFactory().get("/", HTTP_HOST="[::1]:8000")
    assert public_host(request) == "::1"


@pytest.mark.django_db
def test_profile_title_base64_and_update_interval(client, proxy_user, vless_inbound):
    from constance import config

    proxy_user.name = "用户/测试"
    proxy_user.save(update_fields=["name"])
    config.subscription_update_interval = 6
    response = client.get(f"/sub/{proxy_user.reveal_subscription_token()}")
    assert response.status_code == 200
    title = response["Profile-Title"]
    assert title.startswith("base64:")
    assert base64.b64decode(title.removeprefix("base64:")).decode() == "用户/测试@Ostium"
    assert response["Profile-Update-Interval"] == "6"
    assert "%2F" in response["Content-Disposition"]


@pytest.mark.django_db
def test_api_settings_masks_secret_and_rejects_invalid_values(api_client):
    from constance import config

    config.webhook_secret = "top-secret"
    response = api_client.get("/api/v1/settings")
    assert response.json()["webhook_secret"] == "********"
    assert api_client.patch("/api/v1/settings", {"unknown": 1}, format="json").status_code == 400
    assert api_client.patch("/api/v1/settings", {"audit_retention_days": -1}, format="json").status_code == 400
    assert api_client.patch("/api/v1/settings", {"log_level": "nope"}, format="json").status_code == 400
    assert api_client.patch("/api/v1/settings", {"webhook_secret": "********"}, format="json").status_code == 200


@pytest.mark.django_db
def test_read_only_api_key_does_not_receive_uuid(db, admin_user, proxy_user):
    from rest_framework.test import APIClient

    from ostium.accounts.models import ApiKey

    _key, plaintext = ApiKey.objects.create_key(name="reader", scope=ApiKey.Scope.READ, created_by=admin_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    response = client.get("/api/v1/users")
    assert response.status_code == 200
    assert "uuid" not in response.json()["results"][0]


@pytest.mark.django_db
def test_api_unknown_route_returns_problem_json(api_client):
    response = api_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


@pytest.mark.django_db
def test_admin_csp_relaxes_only_admin(admin_client):
    admin_response = admin_client.get("/admin/")
    assert "'unsafe-eval'" in admin_response["Content-Security-Policy"]
    console_response = admin_client.get("/")
    assert "'unsafe-eval'" not in console_response["Content-Security-Policy"]


@pytest.mark.django_db
def test_unverified_totp_session_cannot_read_seed_or_change_password(admin_client, admin_user):
    TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    response = admin_client.get("/accounts/totp/setup/")
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/otp")
    response = admin_client.get("/accounts/password/change/")
    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/otp")


@pytest.mark.django_db
def test_backup_api_delete_removes_file(api_client):
    from ostium import paths
    from ostium.operations.backup import create_backup

    backup = create_backup(password="a-long-backup-password")
    path = paths.backups_dir() / backup.filename
    assert path.exists()
    response = api_client.delete(f"/api/v1/backups/{backup.pk}")
    assert response.status_code == 204
    assert not path.exists()


@pytest.mark.django_db
def test_restore_reencrypts_with_current_field_key(settings):
    backup_key = base64.b64encode(b"b" * 32).decode()
    current_key = settings.OSTIUM_FIELD_KEY
    settings.OSTIUM_FIELD_KEY = backup_key
    try:
        user, _token = create_proxy_user("restored")
        password = user.password
        token = user.reveal_subscription_token()
    finally:
        settings.OSTIUM_FIELD_KEY = current_key
    assert _reencrypt_with_field_key(backup_key) is True
    user.refresh_from_db()
    assert user.password == password
    assert user.reveal_subscription_token() == token


@pytest.mark.django_db
def test_inbound_api_rejects_tcp_port_conflict(api_client, inbounds, certificate):
    trojan = Inbound.objects.get(kind="trojan")
    trojan.certificate = certificate
    trojan.enabled = True
    trojan.port = 443
    response = api_client.patch(
        "/api/v1/inbounds/trojan",
        {"enabled": True, "certificate_domain": certificate.domain, "port": 443},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_rejects_stats_breaking_username(api_client):
    response = api_client.post("/api/v1/users", {"name": "a>b"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_api_cancel_queued_job(api_client):
    from django_q.models import OrmQ
    from django_q.signing import SignedPackage

    queued = OrmQ.objects.create(
        key="ostium",
        payload=SignedPackage.dumps(
            {"id": "queued-api", "name": "queued", "func": "ostium.test", "args": (), "kwargs": {}}
        ),
    )
    response = api_client.post("/api/v1/jobs/queued-api/cancel")
    assert response.status_code == 200
    assert not OrmQ.objects.filter(pk=queued.pk).exists()


def test_webhook_rejects_private_targets():
    with pytest.raises(WebhookError):
        validate_webhook_url("https://127.0.0.1/hook")
    with pytest.raises(WebhookError):
        validate_webhook_url("http://example.com/hook")


def test_webhook_signature_and_delivery(monkeypatch):
    import socket

    import httpx
    import respx

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://hooks.example.com/alert").mock(return_value=httpx.Response(204))
        assert deliver_webhook("https://hooks.example.com/alert", "secret", {"code": "x"}, attempts=1)
        request = route.calls[0].request
        assert request.headers["X-Ostium-Signature"] == sign_payload("secret", request.content)
    assert sign_payload("secret", b"{}").startswith("sha256=")


@pytest.mark.django_db
def test_init_uses_public_base_url_from_environment(settings):
    from constance import config

    settings.OSTIUM_PUBLIC_BASE_URL = "https://vpn.example.com:8443"
    call_command("init", username="envadmin", password="Init-Test-Password-2026", domain="vpn.example.com")
    assert config.public_host == "vpn.example.com"
    assert config.public_base_url == "https://vpn.example.com:8443"
