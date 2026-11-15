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

from ostium.config import Settings
from ostium.db.models import ProxyUser, StatsEpoch, TrafficDaily
from ostium.engine.singbox.v2ray_stats import StatsUnavailable, V2RayStatsClient
from ostium.services.enforcement import DISABLED_REASONS, write_enforcement
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

# A short stats outage is normal during a core reload.  Only a sustained
# outage means quota enforcement can no longer observe new traffic, so raise a
# critical alert after this many seconds instead of silently logging a warning
# forever.
STATS_UNAVAILABLE_ALERT_SECONDS = 300.0


class StatsCollector:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        on_quota: QuotaCallback | None = None,
        interval: float = 5.0,
    ) -> None:
        self.settings = settings
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
        self._pending_lock = asyncio.Lock()
        self._tick = 0
        self._last_error: str | None = None
        self._last_flush = time.monotonic()
        self._pending_disable: set[str] = set()
        self._alerted: dict[str, set[int]] = defaultdict(set)
        self._epochs: dict[str, int] = defaultdict(int)
        self._epoch_pending: dict[str, int] = {}
        self._first_enforce = True
        self._stats_down_since: float | None = None
        self._stats_alerted = False

    async def start(self) -> None:
        if self._task is None:
            await self._load_epochs()
            self._task = asyncio.create_task(self._run(), name="ostium-stats")
            await self.bus.publish("stats.started", {})

    async def _load_epochs(self) -> None:
        """Continue epoch numbering after a process restart.

        Epoch ids only live in memory otherwise, so a restart would reset every
        counter to 1 and create duplicate history rows on the next monthly
        rollover.
        """

        from sqlalchemy import func

        try:
            async with self.session_factory() as session:
                rows = (
                    await session.execute(
                        select(StatsEpoch.user_id, func.max(StatsEpoch.epoch)).group_by(
                            StatsEpoch.user_id
                        )
                    )
                ).all()
            for user_id, epoch in rows:
                if epoch is not None:
                    self._epochs[str(user_id)] = int(epoch)
        except Exception as exc:  # a fresh/legacy database must not block stats
            self.bus.log("warning", "could not restore statistics epochs", error=str(exc))

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
        try:
            counts = await self.client.query_users()
        except StatsUnavailable as exc:
            await self._record_stats_unavailable(exc)
        else:
            self._record_stats_available()
            await self._ingest_counts(counts)
        # Enforcement must not depend on the statistics RPC succeeding.  Core
        # expiry/quota filtering already works from the database, but a user
        # whose row still says "enabled" also needs the disable decision and
        # enforcement policy persisted so a core restart cannot resurrect them.
        self._tick += 1
        if self._tick % 12 == 0:
            await self.flush()
        if self._tick % 6 == 0:
            await self.enforce_quotas()

    async def _ingest_counts(self, counts: dict[str, tuple[int, int]]) -> None:
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
            async with self._pending_lock:
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

    async def _record_stats_unavailable(self, exc: StatsUnavailable) -> None:
        message = str(exc)
        if self._last_error != message:
            self._last_error = message
            self.bus.log("warning", "V2Ray statistics unavailable", error=message)
        now = time.monotonic()
        if self._stats_down_since is None:
            self._stats_down_since = now
        if now - self._stats_down_since >= 60.0:
            # No sample means liveness cannot be proven.  Leaving the last
            # snapshot marked online forever made the dashboard claim active
            # sessions during a multi-hour collector outage.
            for usage in self.usage.values():
                usage.online = False
        if self._stats_alerted or now - self._stats_down_since < STATS_UNAVAILABLE_ALERT_SECONDS:
            return
        self._stats_alerted = True
        try:
            from ostium.services.audit import create_alert

            async with self.session_factory() as session:
                await create_alert(
                    session,
                    self.bus,
                    level="critical",
                    code="stats_unavailable",
                    message=(
                        "V2Ray statistics have been unavailable for more than "
                        f"{int(STATS_UNAVAILABLE_ALERT_SECONDS)} seconds; quota "
                        "accounting and enforcement cannot observe new traffic"
                    ),
                    dedupe_key="v2ray-stats",
                )
                await session.commit()
        except Exception as alert_exc:  # keep the collector alive
            self.bus.log(
                "error", "could not record the statistics outage alert", error=str(alert_exc)
            )

    def _record_stats_available(self) -> None:
        if self._stats_down_since is not None:
            self.bus.log("info", "V2Ray statistics recovered")
        self._stats_down_since = None
        self._stats_alerted = False
        self._last_error = None

    async def flush(self) -> None:
        # ``stop()`` flushes explicitly while the periodic tick may already be
        # inside flush().  Without serialisation both callers can snapshot the
        # same pending counters and bill them twice (or clear them while the
        # first commit is still in flight).
        async with self._flush_lock:
            async with self._pending_lock:
                # Copy the counters: tick() may add new deltas while the
                # database commit below is awaiting.  Clearing the live dict
                # after the commit would silently drop those new bytes.
                pending = {
                    key: _Pending(up=value.up, down=value.down)
                    for key, value in self._pending.items()
                    if value.up or value.down
                }
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
                    # Atomic SQL increment: a concurrent admin reset writes 0,
                    # and the next flush adds only the sample it owns instead
                    # of restoring the pre-reset value from a stale ORM object.
                    await session.execute(
                        update(ProxyUser)
                        .where(ProxyUser.id == user.id)
                        .values(
                            used_bytes=ProxyUser.used_bytes + total,
                            last_seen_at=utcnow(),
                        )
                    )
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
                epochs = dict(self._epoch_pending)
                valid_ids = {user.id for user in users}
                for user_id in list(epochs):
                    if user_id not in valid_ids:
                        # The user was deleted after the epoch was recorded.
                        # Keeping it would make every future flush fail on the
                        # foreign key and block all other users' traffic.
                        self._epoch_pending.pop(user_id, None)
                        epochs.pop(user_id)
                for user_id, epoch in epochs.items():
                    await session.execute(
                        update(StatsEpoch)
                        .where(StatsEpoch.user_id == user_id, StatsEpoch.active.is_(True))
                        .values(active=False)
                    )
                    session.add(StatsEpoch(user_id=user_id, epoch=epoch, active=True))
                await session.commit()
                # Only drop the epochs that were actually committed.  If the
                # commit failed, they stay pending for the next flush; and a
                # newer epoch recorded while the commit was in flight wins.
                for user_id, epoch in epochs.items():
                    if self._epoch_pending.get(user_id) == epoch:
                        self._epoch_pending.pop(user_id, None)
            async with self._pending_lock:
                for key, delta in pending.items():
                    current = self._pending.get(key)
                    if current is None:
                        continue
                    current.up = max(0, current.up - delta.up)
                    current.down = max(0, current.down - delta.down)
                    if current.up == 0 and current.down == 0:
                        self._pending.pop(key, None)
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
        first_enforce = self._first_enforce
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
                # Samples collected before the boundary belong to the old
                # cycle; flushing them after this reset would immediately
                # consume the new quota.
                self._pending.pop(user.id, None)
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
            # Commit unconditionally: threshold alerts are also writes and
            # used to be rolled back when no user state changed.
            await session.commit()
            # Only now is the startup recovery decision durable.  If the
            # commit failed, the next tick must still seed pending disables.
            self._first_enforce = False
            disabled_names = {
                user.name
                for user in users
                if not user.enabled and user.disabled_reason in DISABLED_REASONS
            }
            # Persist the revocation policy before applying it to the running
            # core.  The privileged core reads this file on every start, so a
            # crash between the database commit and the apply can no longer
            # resurrect an over-quota or expired user from stale last-good.
            try:
                write_enforcement(self.settings.paths.enforcement_path, disabled_names)
            except OSError as exc:
                self.bus.log(
                    "error",
                    "could not persist the disabled-user enforcement policy",
                    error=str(exc),
                )
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

    def pending_bytes(self, user_id: str) -> int:
        """Bytes sampled but not yet committed to ``used_bytes``."""

        delta = self._pending.get(user_id)
        return 0 if delta is None else delta.up + delta.down

    def reset_user(self, user_id: str, name: str) -> None:
        """Discard unflushed samples and start a fresh accounting epoch."""

        self._pending.pop(user_id, None)
        self._epochs[user_id] += 1
        self._epoch_pending[user_id] = self._epochs[user_id]
        self._alerted.pop(user_id, None)
        self._last.pop(name, None)
        self.usage.pop(user_id, None)
        self._pending_disable.discard(name)

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
