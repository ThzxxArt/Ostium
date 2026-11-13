"""Traffic accounting, epoch handling and quota enforcement."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ostium.db.models import ProxyUser, StatsEpoch, TrafficDaily
from ostium.engine.singbox.v2ray_stats import StatsUnavailable, V2RayStatsClient
from ostium.services.events import EventBus
from ostium.util.time import as_utc, iso, utcnow


@dataclass
class UserUsage:
    user_id: str
    name: str
    up: int = 0
    down: int = 0
    rate_up: float = 0.0
    rate_down: float = 0.0
    online: bool = False
    last_seen: str | None = None


@dataclass
class _Pending:
    up: int = 0
    down: int = 0


QuotaCallback = Callable[[list[str]], Awaitable[None]]


class StatsCollector:
    def __init__(
        self,
        *,
        settings: object,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        on_quota: QuotaCallback | None = None,
        interval: float = 5.0,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.on_quota = on_quota
        self.interval = interval
        self.client = V2RayStatsClient("127.0.0.1:19091")
        self.usage: dict[str, UserUsage] = {}
        self._pending: dict[str, _Pending] = defaultdict(_Pending)
        self._last: dict[str, tuple[int, int]] = {}
        self._bootstrapped = False
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._flush_lock = asyncio.Lock()
        self._tick = 0
        self._last_error: str | None = None
        self._last_flush = time.monotonic()
        self._pending_disable: set[str] = set()
        self._alerted: dict[str, set[int]] = defaultdict(set)
        self._epochs: dict[str, int] = defaultdict(int)
        self._epoch_pending: dict[str, int] = {}
        self._first_enforce = True

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ostium-stats")
            await self.bus.publish("stats.started", {})

    async def stop(self) -> None:
        # Persist traffic sampled since the last flush before cancelling the
        # loop; otherwise the final interval is silently lost on shutdown.
        try:
            await self.flush()
        except Exception as exc:
            self.bus.log("warning", "final statistics flush failed", error=str(exc))
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.client.close()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except StatsUnavailable as exc:
                if self._last_error != str(exc):
                    self._last_error = str(exc)
                    self.bus.log("warning", "V2Ray statistics unavailable", error=str(exc))
            except Exception as exc:  # keep the loop alive; log once per message
                if self._last_error != str(exc):
                    self._last_error = str(exc)
                    self.bus.log("error", "statistics tick failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except TimeoutError:
                continue

    async def tick(self) -> None:
        counts = await self.client.query_users()
        now = time.monotonic()
        elapsed = max(0.001, now - getattr(self, "_last_tick", now))
        self._last_tick = now
        async with self.session_factory() as session:
            users = (await session.execute(select(ProxyUser))).scalars().all()
        by_name = {user.name: user for user in users}
        for name, (up, down) in counts.items():
            user = by_name.get(name)
            if user is None:
                continue
            previous = self._last.get(name)
            self._last[name] = (up, down)
            if previous is None:
                # First sample after start/reload is a baseline, not usage.
                continue
            delta_up = up - previous[0]
            delta_down = down - previous[1]
            reset = delta_up < 0 or delta_down < 0
            if reset:
                # Counter reset by a core restart/reload; the new epoch starts
                # at zero, so the new sample itself is the first delta.
                delta_up = max(0, up)
                delta_down = max(0, down)
                self._epochs[user.id] += 1
                self._epoch_pending[user.id] = self._epochs[user.id]
            usage = self.usage.setdefault(user.id, UserUsage(user_id=user.id, name=user.name))
            usage.up += delta_up
            usage.down += delta_down
            usage.rate_up = delta_up / elapsed
            usage.rate_down = delta_down / elapsed
            if delta_up or delta_down:
                usage.online = True
                usage.last_seen = iso(utcnow())
            self._pending[user.id].up += delta_up
            self._pending[user.id].down += delta_down
        for name, (up, down) in counts.items():
            if name not in self._last:
                self._last[name] = (up, down)
        # Mark stale online states based on the most recent delta.
        for usage in self.usage.values():
            if usage.last_seen:
                from datetime import datetime

                seen = datetime.fromisoformat(usage.last_seen)
                usage.online = (utcnow() - seen).total_seconds() < 60
        self._tick += 1
        if self._tick % 12 == 0:
            await self.flush()
        if self._tick % 6 == 0:
            await self.enforce_quotas()

    async def flush(self) -> None:
        # ``stop()`` flushes explicitly while the periodic tick may already be
        # inside flush().  Without serialisation both callers can snapshot the
        # same pending counters and bill them twice (or clear them while the
        # first commit is still in flight).
        async with self._flush_lock:
            pending = {key: value for key, value in self._pending.items() if value.up or value.down}
            if not pending:
                self._last_flush = time.monotonic()
                return
            today = utcnow().date()
            async with self.session_factory() as session:
                users = (
                    (
                        await session.execute(
                            select(ProxyUser).where(ProxyUser.id.in_(pending.keys()))
                        )
                    )
                    .scalars()
                    .all()
                )
                for user in users:
                    delta = pending[user.id]
                    total = delta.up + delta.down
                    if total <= 0:
                        continue
                    user.used_bytes += total
                    user.last_seen_at = utcnow()
                    row = (
                        await session.execute(
                            select(TrafficDaily).where(
                                TrafficDaily.user_id == user.id, TrafficDaily.day == today
                            )
                        )
                    ).scalar_one_or_none()
                    if row is None:
                        session.add(
                            TrafficDaily(
                                user_id=user.id,
                                day=today,
                                uplink=delta.up,
                                downlink=delta.down,
                            )
                        )
                    else:
                        row.uplink += delta.up
                        row.downlink += delta.down
                for user_id, epoch in self._epoch_pending.items():
                    await session.execute(
                        update(StatsEpoch)
                        .where(StatsEpoch.user_id == user_id, StatsEpoch.active.is_(True))
                        .values(active=False)
                    )
                    session.add(StatsEpoch(user_id=user_id, epoch=epoch, active=True))
                self._epoch_pending.clear()
                await session.commit()
            self._pending.clear()
            self._last_flush = time.monotonic()
            if self.usage:
                await self.bus.publish(
                    "stats.tick",
                    {
                        "users": [
                            {
                                "id": usage.user_id,
                                "name": usage.name,
                                "up": usage.up,
                                "down": usage.down,
                                "online": usage.online,
                            }
                            for usage in self.usage.values()
                        ]
                    },
                )

    async def enforce_quotas(self) -> None:
        from ostium.services.audit import create_alert

        to_disable: list[str] = []
        reactivated: list[str] = []
        changed = False
        first_enforce = self._first_enforce
        self._first_enforce = False
        now = utcnow()
        async with self.session_factory() as session:
            users = (await session.execute(select(ProxyUser))).scalars().all()
            for user in users:
                if user.quota_cycle != "monthly" or user.cycle_started_at is None:
                    continue
                started = user.cycle_started_at
                if started.year == now.year and started.month == now.month:
                    continue
                # The cycle boundary applies to disabled users too.  A user who
                # hit last month's quota must become usable again instead of
                # staying disabled forever.
                quota_disabled = not user.enabled and user.disabled_reason == "quota_exceeded"
                user.used_bytes = 0
                user.cycle_started_at = now
                changed = True
                self._alerted.pop(user.id, None)
                self._epochs[user.id] += 1
                await session.execute(
                    update(StatsEpoch)
                    .where(StatsEpoch.user_id == user.id, StatsEpoch.active.is_(True))
                    .values(active=False)
                )
                session.add(StatsEpoch(user_id=user.id, epoch=self._epochs[user.id], active=True))
                if quota_disabled:
                    user.enabled = True
                    user.disabled_reason = None
                    reactivated.append(user.name)
            for user in users:
                if (
                    first_enforce
                    and not user.enabled
                    and user.disabled_reason in {"quota_exceeded", "expired"}
                ):
                    # The previous process may have crashed after writing the
                    # database but before the core accepted the change.
                    self._pending_disable.add(user.name)
                if not user.enabled:
                    continue
                pending = self._pending[user.id]
                effective = user.used_bytes + pending.up + pending.down
                if user.expires_at is not None and as_utc(user.expires_at) <= now:
                    user.enabled = False
                    user.disabled_reason = "expired"
                    to_disable.append(user.name)
                    changed = True
                    continue
                if user.quota_bytes > 0:
                    ratio = effective / user.quota_bytes
                    for threshold in (80, 90):
                        if ratio * 100 >= threshold and threshold not in self._alerted[user.id]:
                            self._alerted[user.id].add(threshold)
                            await create_alert(
                                session,
                                self.bus,
                                level="warning" if threshold < 90 else "critical",
                                code=f"quota_{threshold}",
                                message=(
                                    f"user {user.name} has used {ratio * 100:.0f}% of their quota"
                                ),
                                dedupe_key=user.name,
                            )
                            await self.bus.publish(
                                "quota.threshold",
                                {"user": user.name, "percent": threshold},
                            )
                    if effective >= user.quota_bytes:
                        user.enabled = False
                        user.disabled_reason = "quota_exceeded"
                        to_disable.append(user.name)
                        changed = True
            if changed:
                await session.commit()
        if to_disable:
            self._pending_disable.update(to_disable)
            self.bus.log("warning", "users disabled by policy", users=", ".join(to_disable))
            await self.bus.publish("quota.exceeded", {"users": to_disable})
        if reactivated:
            self._pending_disable.update(reactivated)
            self.bus.log("info", "users re-enabled after quota reset", users=", ".join(reactivated))
            await self.bus.publish("quota.reset", {"users": reactivated})
        if self._pending_disable:
            names = sorted(self._pending_disable)
            if await self._disable(names):
                self._pending_disable.difference_update(names)

    async def _disable(self, names: list[str]) -> bool:
        if self.on_quota is not None:
            try:
                await self.on_quota(names)
            except Exception as exc:
                self.bus.log("error", "failed to apply quota configuration", error=str(exc))
                return False
        return True

    def snapshot(self) -> dict[str, object]:
        users = list(self.usage.values())
        return {
            "online": sum(1 for user in users if user.online),
            "rate_up": sum(user.rate_up for user in users),
            "rate_down": sum(user.rate_down for user in users),
            "users": [
                {
                    "id": user.user_id,
                    "name": user.name,
                    "up": user.up,
                    "down": user.down,
                    "rate_up": user.rate_up,
                    "rate_down": user.rate_down,
                    "online": user.online,
                    "last_seen": user.last_seen,
                }
                for user in users
            ],
            "last_error": self._last_error,
        }


async def usage_series(
    session: AsyncSession, *, days: int = 30, user_id: str | None = None
) -> list[dict[str, object]]:
    start = utcnow().date() - timedelta(days=days - 1)
    query = select(TrafficDaily).where(TrafficDaily.day >= start)
    if user_id:
        query = query.where(TrafficDaily.user_id == user_id)
    rows = (await session.execute(query)).scalars().all()
    buckets: dict[date, dict[str, int]] = {}
    for row in rows:
        bucket = buckets.setdefault(row.day, {"up": 0, "down": 0})
        bucket["up"] += row.uplink
        bucket["down"] += row.downlink
    return [
        {"day": day.isoformat(), "up": value["up"], "down": value["down"]}
        for day, value in sorted(buckets.items())
    ]


async def record_epoch(session: AsyncSession, user_id: str, epoch: int) -> None:
    session.add(StatsEpoch(user_id=user_id, epoch=epoch))
    await session.flush()


@dataclass
class SpeedSample:
    up: int = 0
    down: int = 0
    samples: list[tuple[int, int]] = field(default_factory=list)
