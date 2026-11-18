"""Proxy service query helpers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from ostium.proxy.models import TrafficDaily
from ostium.proxy.services import (
    account_usage,
    active_queryset,
    config_queryset,
    enabled_inbounds,
    initialize_inbounds,
)


@pytest.mark.django_db
def test_active_querysets(proxy_user):
    disabled, _ = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("off")
    disabled.disable()
    expired, _ = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("expired")
    expired.expires_at = timezone.now() - timedelta(seconds=1)
    expired.save()
    over, _ = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("over")
    over.quota_bytes = 1
    over.used_bytes = 2
    over.save()
    names = set(active_queryset().values_list("name", flat=True))
    assert names == {"alice"}
    assert list(config_queryset().values_list("name", flat=True)) == ["alice"]


@pytest.mark.django_db
def test_enabled_inbounds(proxy_user):
    initialize_inbounds(enable=("vless",))
    assert [item.kind for item in enabled_inbounds()] == ["vless"]


@pytest.mark.django_db
def test_initialize_inbounds_idempotent():
    first = initialize_inbounds(enable=("vless",))
    second = initialize_inbounds(enable=("vless",))
    assert len(first) == len(second) == 4
    assert InboundCount() == 4


def InboundCount():
    from ostium.proxy.models import Inbound

    return Inbound.objects.count()


@pytest.mark.django_db
def test_account_usage(proxy_user):
    TrafficDaily.objects.create(user=proxy_user, day=date.today(), uplink=1, downlink=2)
    TrafficDaily.objects.create(user=proxy_user, day=date.today() - timedelta(days=1), uplink=3, downlink=4)
    rows = account_usage(proxy_user)
    assert len(rows) == 2
    assert rows[0]["uplink"] == 1
