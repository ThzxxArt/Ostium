"""Unit coverage for review fixes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from ostium.api.errors import APIProblemMiddleware, api_not_found
from ostium.api.throttles import OstiumAPIThrottle
from ostium.operations.runtime_settings import SettingValidationError, coerce_setting
from ostium.operations.webhook import (
    WebhookError,
    alert_payload,
    deliver_webhook,
    notify_alert,
    validate_webhook_url,
)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("block_private_egress", "yes"),
        ("traffic_retention_days", "x"),
        ("traffic_retention_days", -1),
        ("subscription_update_interval", 0),
        ("auto_backup_keep", 101),
        ("server_name", ""),
        ("server_name", "x" * 101),
        ("server_dns_mode", "bad"),
        ("log_level", "bad"),
        ("server_dns_doh_url", "http://example.com"),
        ("server_dns_doh_url", "https://user:pass@example.com"),
        ("public_base_url", "ftp://example.com"),
        ("public_host", "https://example.com"),
        ("public_host", "vpn.example.com:8443"),
        ("webhook_secret", "x" * 257),
        ("unknown", "x"),
    ],
)
def test_runtime_setting_rejects_invalid_values(key, value):
    with pytest.raises(SettingValidationError):
        coerce_setting(key, value)


def test_runtime_setting_text_and_credentials():
    with pytest.raises(SettingValidationError):
        coerce_setting("server_name", 123)
    with pytest.raises(SettingValidationError):
        coerce_setting("server_name", "bad\x00name")
    with pytest.raises(SettingValidationError):
        coerce_setting("public_base_url", "https://user:pass@example.com")
    with pytest.raises(SettingValidationError):
        coerce_setting("public_host", "vpn.example.com/path")


def test_runtime_setting_accepts_valid_values():
    assert coerce_setting("server_name", " Ostium ") == "Ostium"
    assert coerce_setting("public_host", "[::1]") == "::1"
    assert coerce_setting("public_base_url", "https://vpn.example.com:8443/") == "https://vpn.example.com:8443"
    assert coerce_setting("log_level", "debug") == "debug"


def test_webhook_url_validation_branches(monkeypatch):
    with pytest.raises(WebhookError):
        validate_webhook_url("https:///missing")
    with pytest.raises(WebhookError):
        validate_webhook_url("https://user:pass@example.com/x")
    with pytest.raises(WebhookError):
        validate_webhook_url("https://10.0.0.1/x")
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(WebhookError):
        validate_webhook_url("https://example.com/x")
    monkeypatch.setattr("socket.getaddrinfo", Mock(side_effect=OSError("dns")))
    with pytest.raises(WebhookError):
        validate_webhook_url("https://example.com/x")


def test_deliver_webhook_retries_and_requires_secret(monkeypatch):
    with pytest.raises(WebhookError):
        deliver_webhook("https://example.com", "", {})
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=500)

    import ostium.operations.webhook as webhook_module

    monkeypatch.setattr(webhook_module.httpx, "Client", FailingClient)
    assert deliver_webhook("https://example.com", "secret", {}, attempts=2) is False

    class RaisingClient(FailingClient):
        def post(self, *args, **kwargs):
            raise webhook_module.httpx.ConnectError("down")

    monkeypatch.setattr(webhook_module.httpx, "Client", RaisingClient)
    assert deliver_webhook("https://example.com", "secret", {}, attempts=1) is False


@pytest.mark.django_db
def test_notify_alert_noop_and_payload(monkeypatch):
    alert = SimpleNamespace(
        pk=1,
        code="x",
        level="warning",
        message="m",
        detail={},
        fingerprint="x",
        first_seen_at=__import__("django.utils.timezone", fromlist=["now"]).now(),
        last_seen_at=__import__("django.utils.timezone", fromlist=["now"]).now(),
    )
    payload = alert_payload(alert)
    assert payload["code"] == "x"
    notify_alert(alert, background=False)
    from constance import config

    config.webhook_url = ""
    notify_alert(alert, background=False)
    config.webhook_url = "https://hooks.example.com/x"
    config.webhook_secret = "secret"
    called = {}
    monkeypatch.setattr("ostium.operations.webhook.deliver_webhook", lambda *args, **kwargs: called.setdefault("x", 1))
    notify_alert(alert, background=False)
    assert called["x"] == 1


def test_api_problem_middleware():
    def boom(request):
        raise RuntimeError("boom")

    request = RequestFactory().get("/api/v1/x")
    response = APIProblemMiddleware(boom)(request)
    assert response.status_code == 500
    assert response["Content-Type"].startswith("application/problem+json")
    with pytest.raises(RuntimeError):
        APIProblemMiddleware(boom)(RequestFactory().get("/console/x"))

    missing = api_not_found(RequestFactory().get("/api/v1/x"))
    assert missing.status_code == 404
    ok = APIProblemMiddleware(lambda request: SimpleNamespace(status_code=200))(request)
    assert ok.status_code == 200

    from rest_framework.exceptions import ValidationError

    from ostium.api.errors import exception_handler

    request = RequestFactory().get("/api/v1/x")
    assert exception_handler(RuntimeError("x"), {"request": request}) is None
    response = exception_handler(ValidationError({"name": ["bad"]}), {"request": request})
    assert response.status_code == 400


def test_api_throttle_read_and_write():
    cache.clear()
    read = RequestFactory().get("/api/v1/users")
    read.api_key = SimpleNamespace(pk="key")
    throttle = OstiumAPIThrottle()
    assert all(throttle.allow_request(read, None) for _ in range(120))
    assert throttle.allow_request(read, None) is False
    assert throttle.wait() is not None

    cache.clear()
    no_key = RequestFactory().get("/api/v1/users")
    assert OstiumAPIThrottle().allow_request(no_key, None) is True

    original_incr = cache.incr

    def flaky_incr(key, *args, **kwargs):
        cache.incr = original_incr
        raise ValueError

    cache.incr = flaky_incr
    assert OstiumAPIThrottle().allow_request(read, None) is True

    cache.clear()
    write = RequestFactory().post("/api/v1/users")
    write.api_key = SimpleNamespace(pk="key2")
    throttle = OstiumAPIThrottle()
    assert all(throttle.allow_request(write, None) for _ in range(30))
    assert throttle.allow_request(write, None) is False


def test_proxy_client_ip_middleware():
    from ostium.accounts.middleware import ProxyClientIPMiddleware

    seen = {}

    def capture(request):
        seen["ip"] = request.META["REMOTE_ADDR"]
        return SimpleNamespace(status_code=200)

    request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1, 8.8.8.8")
    with override_settings(OSTIUM_BEHIND_PROXY=True):
        ProxyClientIPMiddleware(capture)(request)
    assert seen["ip"] == "8.8.8.8"

    request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="bad")
    with override_settings(OSTIUM_BEHIND_PROXY=True):
        ProxyClientIPMiddleware(capture)(request)
    assert seen["ip"] == "127.0.0.1"
