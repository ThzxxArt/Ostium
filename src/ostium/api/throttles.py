"""API-key scoped throttling: reads 120/min, writes 30/min."""

from __future__ import annotations

import time

from django.core.cache import cache
from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import BaseThrottle


class OstiumAPIThrottle(BaseThrottle):
    def allow_request(self, request, view) -> bool:
        if not hasattr(request, "api_key"):
            # Permission checks run before throttles; this is only a guard.
            return True
        scope = "read" if request.method in SAFE_METHODS else "write"
        limit = 120 if scope == "read" else 30
        window = int(time.time() // 60)
        key = f"ostium:api:{scope}:{request.api_key.pk}:{window}"
        cache.add(key, 0, timeout=120)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=120)
            count = 1
        self.retry_after = max(1, 60 - int(time.time() % 60))
        return count <= limit

    def wait(self) -> float | None:
        return float(self.retry_after)


__all__ = ["OstiumAPIThrottle"]
