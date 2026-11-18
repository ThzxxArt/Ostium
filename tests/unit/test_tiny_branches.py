"""Remaining tiny model branches."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ostium.certificates.models import Certificate


@pytest.mark.django_db
def test_quota_helpers(proxy_user):
    proxy_user.quota_bytes = 0
    assert proxy_user.quota_percent is None
    assert proxy_user.remaining_bytes is None
    proxy_user.quota_bytes = 100
    proxy_user.used_bytes = 30
    assert proxy_user.quota_percent == 30.0
    assert proxy_user.remaining_bytes == 70
    proxy_user.last_seen_at = timezone.now()
    assert proxy_user.is_online is True
    proxy_user.last_seen_at = timezone.now() - timedelta(minutes=5)
    assert proxy_user.is_online is False


@pytest.mark.django_db
def test_certificate_tones(certificate):
    certificate.expires_at = timezone.now() + timedelta(days=10)
    assert certificate.expiry_tone == "danger"
    certificate.expires_at = timezone.now() + timedelta(days=20)
    assert certificate.expiry_tone == "warning"
    certificate.expires_at = timezone.now() + timedelta(days=90)
    assert certificate.expiry_tone == "success"
    certificate.expires_at = timezone.now() - timedelta(days=1)
    assert certificate.expiry_tone == "danger"
    assert certificate.status == Certificate.Status.READY
