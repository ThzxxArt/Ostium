"""Small in-process sliding-window limiter for login and public subscriptions."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_window: float = 3600.0) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._max_window = max_window
        self._calls = 0

    def _cleanup(self, now: float) -> None:
        """Drop idle keys; a spoofed-IP flood must not grow memory forever."""

        for key, bucket in list(self._events.items()):
            if not bucket or now - bucket[-1] > self._max_window:
                self._events.pop(key, None)

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % 512 == 0:
            self._cleanup(now)
        bucket = self._events[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)


LIMITER = SlidingWindowLimiter()
