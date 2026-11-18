"""Small branch coverage helpers."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ostium.formatting import format_datetime, format_duration, relative_time
from ostium.proxy.services import mark_dirty, parse_size
from ostium.subscriptions.services import subscription_url, userinfo_header


def test_version_file(tmp_path, monkeypatch):
    from ostium import version

    (tmp_path / "VERSION").write_text("7.7.7\n")
    monkeypatch.setenv("OSTIUM_ROOT", str(tmp_path))
    monkeypatch.setattr(version, "_read_version_file", lambda: "7.7.7")
    monkeypatch.setattr(version, "version", lambda name: (_ for _ in ()).throw(version.PackageNotFoundError()))
    assert version.get_version() == "7.7.7"


def test_relative_time_branches():
    now = timezone.now()
    assert relative_time(now - timedelta(seconds=10)).endswith("s ago")
    assert relative_time(now - timedelta(minutes=5)).endswith("m ago")
    assert relative_time(now - timedelta(hours=2)).endswith("h ago")
    assert relative_time(now - timedelta(days=3)).endswith("d ago")
    assert format_duration(3600) == "1h 0m"
    assert ":" in format_datetime(now)


def test_parse_size_edges():
    assert parse_size("0") == 0
    assert parse_size("10") == 10
    with pytest.raises(ValueError):
        parse_size("-1G")


@pytest.mark.django_db
def test_mark_dirty_increments():
    from ostium.operations.models import RuntimeState

    before = RuntimeState.load().desired_revision
    assert mark_dirty() == before + 1


@pytest.mark.django_db
def test_userinfo_with_daily_and_expiry(proxy_user):
    from datetime import date

    from ostium.proxy.models import TrafficDaily

    TrafficDaily.objects.create(user=proxy_user, day=date.today(), uplink=10, downlink=20)
    proxy_user.expires_at = timezone.now() + timedelta(days=10)
    proxy_user.save(update_fields=["expires_at"])
    header = userinfo_header(proxy_user)
    assert "upload=10" in header
    assert "download=20" in header
    assert "expire=0" not in header


@pytest.mark.django_db
def test_subscription_url_fallback(proxy_user, settings):
    settings.OSTIUM_PUBLIC_BASE_URL = ""
    from constance import config

    config.public_base_url = ""
    config.public_host = ""
    url = subscription_url(proxy_user, "clash")
    assert url.startswith("http://127.0.0.1:8000/sub/")
    assert url.endswith("/clash")


@pytest.mark.django_db
def test_quota_warnings(proxy_user):
    from ostium.operations.models import Alert
    from ostium.proxy.services import enforce_limits

    proxy_user.quota_bytes = 100
    proxy_user.used_bytes = 85
    proxy_user.save()
    enforce_limits()
    assert Alert.objects.filter(code="quota_80").exists()
