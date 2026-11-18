"""Token and user lifecycle tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ostium.proxy.models import ProxyUser, hash_subscription_token
from ostium.proxy.services import create_proxy_user, parse_size


@pytest.mark.django_db
def test_token_is_hashed_and_revealable(proxy_user):
    token = proxy_user.reveal_subscription_token()
    assert len(token) >= 40
    assert proxy_user.subscription_token_hash == hash_subscription_token(token)
    assert token not in proxy_user.subscription_token_hash


@pytest.mark.django_db
def test_rotate_token_invalidates_old(proxy_user):
    old = proxy_user.reveal_subscription_token()
    new = proxy_user.rotate_subscription_token()
    proxy_user.refresh_from_db()
    assert new != old
    assert proxy_user.subscription_token_hash == hash_subscription_token(new)
    assert ProxyUser.objects.filter(subscription_token_hash=hash_subscription_token(old)).count() == 0


@pytest.mark.django_db
def test_status_transitions(proxy_user):
    assert proxy_user.status == "active"
    proxy_user.expires_at = timezone.now() - timedelta(seconds=1)
    proxy_user.save(update_fields=["expires_at"])
    assert proxy_user.status == "expired"
    assert not proxy_user.is_active
    proxy_user.expires_at = None
    proxy_user.quota_bytes = 10
    proxy_user.used_bytes = 10
    proxy_user.save(update_fields=["expires_at", "quota_bytes", "used_bytes"])
    assert proxy_user.status == "quota_exceeded"
    proxy_user.enabled = False
    assert proxy_user.status == "disabled"


@pytest.mark.django_db
def test_monthly_rollover_reenables_quota_user(proxy_user):
    proxy_user.quota_cycle = ProxyUser.QuotaCycle.MONTHLY
    proxy_user.used_bytes = proxy_user.quota_bytes
    proxy_user.enabled = False
    proxy_user.disabled_reason = ProxyUser.DisabledReason.QUOTA_EXCEEDED
    proxy_user.cycle_started_at = timezone.now() - timedelta(days=40)
    proxy_user.save()
    assert proxy_user.roll_month_if_needed() is True
    assert proxy_user.used_bytes == 0
    assert proxy_user.enabled is True
    assert proxy_user.status == "active"


def test_parse_size():
    assert parse_size("1K") == 1024
    assert parse_size("1.5G") == int(1.5 * 1024**3)
    assert parse_size("2TiB") == 2 * 1024**4
    assert parse_size(0) == 0
    with pytest.raises(ValueError):
        parse_size("nope")


@pytest.mark.django_db
def test_create_user_generates_credentials():
    user, token = create_proxy_user("bob")
    assert user.uuid
    assert user.password
    assert user.ss_password
    assert token == user.reveal_subscription_token()
    assert user.cycle_started_at is not None
