"""Statistics sampler and quota enforcement tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from ostium.engine import stats as stats_module
from ostium.engine.stats import StatsSampler, query_stats
from ostium.proxy.models import ProxyUser, StatsEpoch, TrafficDaily
from ostium.proxy.services import enforce_limits


def test_proto_messages_build():
    request = stats_module.QueryStatsRequest()
    request.pattern = ".*"
    assert request.SerializeToString()
    response = stats_module.QueryStatsResponse()
    assert response.stat == []


def test_query_stats_parses(monkeypatch):
    class FakeCall:
        def __call__(self, request, timeout=None):
            response = stats_module.QueryStatsResponse()
            for name, value in (
                ("user>>>alice>>>traffic>>>uplink", 10),
                ("user>>>alice>>>traffic>>>downlink", 20),
                ("inbound>>>x>>>traffic>>>uplink", 5),
            ):
                stat = response.stat.add()
                stat.name = name
                stat.value = value
            return response

    class FakeChannel:
        def unary_unary(self, *args, **kwargs):
            return FakeCall()

        def close(self):
            pass

    monkeypatch.setattr(stats_module.grpc, "insecure_channel", lambda address: FakeChannel())
    assert query_stats() == {"alice": (10, 20)}


@pytest.mark.django_db
def test_sampler_delta_and_flush(proxy_user, monkeypatch):
    values = iter(
        [
            {"alice": (100, 200)},
            {"alice": (130, 260)},
        ]
    )
    monkeypatch.setattr(stats_module, "query_stats", lambda: next(values))
    sampler = StatsSampler()
    assert sampler.sample() is True
    assert sampler.pending == {}
    sampler.last_sample_at = timezone.now() - timedelta(seconds=5)
    assert sampler.sample() is True
    assert sampler.pending["alice"] == [30, 60]
    assert sampler.flush() == 1
    proxy_user.refresh_from_db()
    assert proxy_user.used_bytes == 90
    assert proxy_user.last_seen_at is not None
    row = TrafficDaily.objects.get(user=proxy_user, day=date.today())
    assert row.uplink == 30
    assert row.downlink == 60


@pytest.mark.django_db
def test_sampler_counter_reset_rotates_epoch(proxy_user, monkeypatch):
    values = iter(
        [
            {"alice": (100, 200)},
            {"alice": (10, 20)},
        ]
    )
    monkeypatch.setattr(stats_module, "query_stats", lambda: next(values))
    sampler = StatsSampler()
    sampler.sample()
    sampler.last_sample_at = timezone.now() - timedelta(seconds=5)
    sampler.sample()
    assert sampler.pending["alice"] == [10, 20]
    assert StatsEpoch.objects.filter(user=proxy_user, active=True).count() == 1


@pytest.mark.django_db
def test_sampler_handles_unavailable(monkeypatch):
    def fail():
        raise stats_module.StatsUnavailable("down")

    monkeypatch.setattr(stats_module, "query_stats", fail)
    sampler = StatsSampler()
    assert sampler.sample() is False
    assert sampler.stats_ok is False
    assert sampler.failures == 1


@pytest.mark.django_db
def test_enforce_quota_disables_user(proxy_user):
    proxy_user.quota_bytes = 100
    proxy_user.used_bytes = 100
    proxy_user.save()
    assert enforce_limits() is True
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is False
    assert proxy_user.disabled_reason == ProxyUser.DisabledReason.QUOTA_EXCEEDED


@pytest.mark.django_db
def test_enforce_expiry(proxy_user):
    proxy_user.expires_at = timezone.now() - timedelta(minutes=1)
    proxy_user.save()
    enforce_limits()
    proxy_user.refresh_from_db()
    assert proxy_user.status == "expired"


@pytest.mark.django_db
def test_flush_skips_unknown_users(proxy_user, monkeypatch):
    sampler = StatsSampler(pending={"nobody": [1, 2]})
    assert sampler.flush() == 0
    assert sampler.pending == {}
