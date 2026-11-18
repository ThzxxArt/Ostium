"""Model string/display branches."""

from __future__ import annotations

from datetime import date

import pytest
from django.utils import timezone

from ostium.operations.models import Alert, AuditEvent, Backup, RuntimeState
from ostium.proxy.models import StatsEpoch, TrafficDaily


@pytest.mark.django_db
def test_model_strings(proxy_user, inbounds, certificate):
    assert str(proxy_user) == proxy_user.name
    assert str(inbounds[0])
    assert str(StatsEpoch.objects.get(user=proxy_user))
    assert str(TrafficDaily.objects.create(user=proxy_user, day=date.today(), uplink=1, downlink=1))
    assert str(certificate) == certificate.domain
    alert = Alert.objects.create(code="x", fingerprint="x", message="m")
    assert "x" in str(alert)
    assert str(AuditEvent.objects.create(action="a"))
    assert str(Backup.objects.create(filename="f"))
    assert "rev" in str(RuntimeState.load())


@pytest.mark.django_db
def test_runtime_properties():
    state = RuntimeState.load()
    assert state.heartbeat_age is None
    state.worker_heartbeat = timezone.now()
    assert state.worker_alive is True
    state.applied_revision = 2
    state.desired_revision = 2
    state.singbox_running = True
    assert state.is_converged is True


@pytest.mark.django_db
def test_inbound_labels(inbounds):
    for inbound in inbounds:
        assert inbound.label
        assert inbound.short_label
        assert inbound.needs_certificate == (inbound.kind in {"hysteria2", "trojan"})
