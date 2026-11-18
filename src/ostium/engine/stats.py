"""Data-plane traffic accounting from the V2Ray stats API."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import grpc
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ostium.proxy.models import ProxyUser, StatsEpoch, TrafficDaily

from .proto.stats import SERVICE, QueryStatsRequest, QueryStatsResponse
from .runtime import write_usage

logger = logging.getLogger("ostium.engine.stats")

USER_STAT_RE = re.compile(r"^user>>>(?P<user>[^>]+)>>>traffic>>>(?P<direction>uplink|downlink)$")


class StatsUnavailable(RuntimeError):
    pass


def query_stats(address: str | None = None, *, timeout: float = 5.0) -> dict[str, tuple[int, int]]:
    address = address or settings.OSTIUM_SINGBOX_STATS_ADDRESS
    channel = grpc.insecure_channel(address)
    try:
        call = channel.unary_unary(
            SERVICE,
            request_serializer=lambda message: message.SerializeToString(),
            response_deserializer=QueryStatsResponse.FromString,
        )
        request = QueryStatsRequest()
        request.pattern = ".*"
        response = call(request, timeout=timeout)
        totals: dict[str, list[int]] = {}
        for stat in response.stat:
            match = USER_STAT_RE.match(stat.name)
            if not match:
                continue
            key = match.group("user")
            bucket = totals.setdefault(key, [0, 0])
            bucket[0 if match.group("direction") == "uplink" else 1] += int(stat.value)
        return {name: (values[0], values[1]) for name, values in totals.items()}
    except grpc.RpcError as exc:
        raise StatsUnavailable(str(exc)) from exc
    finally:
        channel.close()


@dataclass
class UserRate:
    uplink: float = 0.0
    downlink: float = 0.0
    last_activity: datetime | None = None


@dataclass
class StatsSampler:
    baseline: dict[str, tuple[int, int]] = field(default_factory=dict)
    pending: dict[str, list[int]] = field(default_factory=dict)
    rates: dict[str, UserRate] = field(default_factory=dict)
    last_sample_at: datetime | None = None
    stats_ok: bool = False
    initialized: bool = False
    failures: int = 0
    total_uplink: int = 0
    total_downlink: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def sample(self) -> bool:
        now = timezone.now()
        try:
            totals = query_stats()
        except StatsUnavailable as exc:
            self.failures += 1
            self.stats_ok = False
            if self.failures in {1, 12, 60}:
                logger.warning("stats unavailable: %s", exc)
            for rate in self.rates.values():
                rate.uplink = 0.0
                rate.downlink = 0.0
            self._publish()
            return False

        self.failures = 0
        self.stats_ok = True
        elapsed = 5.0
        if self.last_sample_at is not None:
            elapsed = max(0.5, (now - self.last_sample_at).total_seconds())
        self.last_sample_at = now

        if not self.initialized:
            # First successful sample establishes the baseline. A user who
            # first appears later is counted from zero rather than dropped.
            self.baseline = dict(totals)
            self.initialized = True
            for name in totals:
                self.rates.setdefault(name, UserRate())
            self._publish()
            return True

        for name, current in totals.items():
            previous = self.baseline.get(name)
            if previous is None:
                previous = (0, 0)
                self.baseline[name] = previous
            if current[0] < previous[0] or current[1] < previous[1]:
                # sing-box restarted and counters were reset. Count the new
                # value in a fresh epoch.
                self._rotate_epoch(name, now)
                delta_up, delta_down = current
            else:
                delta_up = current[0] - previous[0]
                delta_down = current[1] - previous[1]
            self.baseline[name] = current
            if delta_up or delta_down:
                bucket = self.pending.setdefault(name, [0, 0])
                bucket[0] += delta_up
                bucket[1] += delta_down
                rate = self.rates.setdefault(name, UserRate())
                rate.uplink = delta_up / elapsed
                rate.downlink = delta_down / elapsed
                rate.last_activity = now
            else:
                rate = self.rates.setdefault(name, UserRate())
                if rate.last_activity is None or (now - rate.last_activity).total_seconds() > 10:
                    rate.uplink = 0.0
                    rate.downlink = 0.0

        for name, rate in self.rates.items():
            if name not in totals and (rate.last_activity is None or (now - rate.last_activity).total_seconds() > 10):
                rate.uplink = 0.0
                rate.downlink = 0.0

        self._publish()
        return True

    def _rotate_epoch(self, name: str, now: datetime) -> None:
        try:
            user = ProxyUser.objects.filter(name=name).only("pk").first()
            if user is None:
                return
            StatsEpoch.objects.filter(user_id=user.pk, active=True).update(active=False, ended_at=now)
            StatsEpoch.objects.create(user_id=user.pk, active=True, started_at=now)
        except Exception:
            logger.exception("could not rotate stats epoch for %s", name)

    def _publish(self) -> None:
        users = {
            name: {
                "uplink_rate": round(rate.uplink, 2),
                "downlink_rate": round(rate.downlink, 2),
                "online": bool(rate.last_activity and (timezone.now() - rate.last_activity).total_seconds() < 60),
                "last_activity": rate.last_activity.isoformat() if rate.last_activity else None,
            }
            for name, rate in self.rates.items()
        }
        write_usage(
            {
                "stats_ok": self.stats_ok,
                "users": users,
                "pending_users": len(self.pending),
                "total_uplink": self.total_uplink,
                "total_downlink": self.total_downlink,
            }
        )

    def flush(self) -> int:
        """Persist pending deltas. Safe to call repeatedly.

        Pending counters are only removed after the database transaction has
        committed. If the transaction fails, the in-memory counters must stay
        intact so the next flush can retry without losing traffic.
        """

        with self._lock:
            if not self.pending:
                return 0
            now = timezone.now()
            today = timezone.localdate()
            names = list(self.pending)
            users = {user.name: user for user in ProxyUser.objects.filter(name__in=names)}
            flushed: list[tuple[str, int, int]] = []
            with transaction.atomic():
                for name, (uplink, downlink) in list(self.pending.items()):
                    user = users.get(name)
                    if user is None or uplink + downlink <= 0:
                        continue
                    total = uplink + downlink
                    ProxyUser.objects.filter(pk=user.pk).update(
                        used_bytes=F("used_bytes") + total,
                        uploaded_bytes=F("uploaded_bytes") + uplink,
                        downloaded_bytes=F("downloaded_bytes") + downlink,
                        last_seen_at=now,
                    )
                    row, created = TrafficDaily.objects.get_or_create(
                        user_id=user.pk,
                        day=today,
                        defaults={"uplink": uplink, "downlink": downlink},
                    )
                    if not created:
                        TrafficDaily.objects.filter(pk=row.pk).update(
                            uplink=F("uplink") + uplink,
                            downlink=F("downlink") + downlink,
                        )
                    flushed.append((name, uplink, downlink))

            # Commit succeeded: subtract exactly what was persisted. Any bytes
            # sampled concurrently remain pending for the next flush.
            for name, uplink, downlink in flushed:
                bucket = self.pending.get(name)
                if bucket is not None:
                    bucket[0] = max(0, bucket[0] - uplink)
                    bucket[1] = max(0, bucket[1] - downlink)
                    if bucket[0] + bucket[1] <= 0:
                        self.pending.pop(name, None)
                self.total_uplink += uplink
                self.total_downlink += downlink
            for name in [
                name for name, bucket in self.pending.items() if name not in users or bucket[0] + bucket[1] <= 0
            ]:
                self.pending.pop(name, None)
            self._publish()
            return len(flushed)

    def snapshot(self) -> dict[str, Any]:
        return {
            "stats_ok": self.stats_ok,
            "pending": {name: list(value) for name, value in self.pending.items()},
            "rates": {
                name: {
                    "uplink_rate": rate.uplink,
                    "downlink_rate": rate.downlink,
                    "online": bool(rate.last_activity and (timezone.now() - rate.last_activity).total_seconds() < 60),
                }
                for name, rate in self.rates.items()
            },
        }
