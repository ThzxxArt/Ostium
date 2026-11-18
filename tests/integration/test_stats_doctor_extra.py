"""Stats and doctor branch coverage."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ostium.engine import stats as stats_module
from ostium.engine.stats import StatsSampler
from ostium.operations import doctor as doctor_module
from ostium.operations.doctor import doctor_summary, run_doctor


@pytest.mark.django_db
def test_sampler_snapshot_and_stale(proxy_user, monkeypatch):
    values = iter([{"alice": (1, 2), "gone": (3, 4)}, {"alice": (5, 6)}])
    monkeypatch.setattr(stats_module, "query_stats", lambda: next(values))
    sampler = StatsSampler()
    sampler.sample()
    sampler.last_sample_at = timezone.now() - timedelta(seconds=5)
    sampler.sample()
    # A temporarily idle user keeps its baseline so its next counters are
    # still accounted for instead of being dropped.
    assert sampler.baseline["gone"] == (3, 4)
    snapshot = sampler.snapshot()
    assert snapshot["rates"]["alice"]["uplink_rate"] > 0


@pytest.mark.django_db
def test_sampler_rotate_epoch_unknown():
    sampler = StatsSampler()
    sampler._rotate_epoch("nobody", timezone.now())


@pytest.mark.django_db
def test_sampler_flush_empty():
    assert StatsSampler().flush() == 0


@pytest.mark.django_db
def test_sampler_publish_offline(monkeypatch):
    values = iter([{"alice": (1, 2)}])
    monkeypatch.setattr(stats_module, "query_stats", lambda: next(values))
    sampler = StatsSampler()
    sampler.sample()
    sampler.rates["alice"].last_activity = timezone.now() - timedelta(minutes=5)
    sampler._publish()
    from ostium.engine.runtime import read_usage

    assert read_usage()["users"]["alice"]["online"] is False


@pytest.mark.django_db
def test_doctor_failure_branches(monkeypatch):
    # Force the binary check to fail and disk below the threshold.
    monkeypatch.setattr(doctor_module, "verify_binary", lambda: (False, "missing"))
    monkeypatch.setattr(doctor_module, "disk_free_bytes", lambda: 10)
    monkeypatch.setattr(doctor_module, "doh_available", lambda url: False)
    checks = run_doctor()
    names = {check["name"]: check["status"] for check in checks}
    assert names["sing-box binary"] == "fail"
    assert names["Disk space"] == "fail"
    assert names["DoH"] == "warn"
    assert doctor_summary(checks)["fail"] >= 2


@pytest.mark.django_db
def test_doctor_pending_migrations(monkeypatch):
    class Executor:
        def __init__(self, connection):
            pass

        def load_loader_marker(self):
            pass

        def load_disk(self):
            pass

    class Graph:
        def leaf_nodes(self):
            return []

    class Loader:
        graph = Graph()

    class PlanExecutor:
        loader = Loader()

        def __init__(self, connection):
            pass

        def migration_plan(self, targets):
            return [(object(), False)]

    monkeypatch.setattr(doctor_module, "MigrationExecutor", PlanExecutor)
    checks = run_doctor()
    assert any(check["name"] == "Migrations" and check["status"] == "fail" for check in checks)


@pytest.mark.django_db
def test_doctor_alerts_and_tls(monkeypatch, certificate):
    from django.contrib.auth import get_user_model
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from ostium.operations.models import Alert

    user = get_user_model().objects.create_superuser("doc", "d@e.f", "Doc-Password-2026")
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    Alert.objects.create(code="x", fingerprint="x", message="x")
    checks = run_doctor()
    names = {check["name"]: check["status"] for check in checks}
    assert names["Two-factor authentication"] == "pass"
    assert names["Alerts"] == "warn"
