"""Health, readiness and Prometheus endpoints."""

from __future__ import annotations

import shutil

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from ostium import paths
from ostium.engine.runtime import read_usage
from ostium.operations.models import Alert, RuntimeState
from ostium.version import __version__

REGISTRY = CollectorRegistry(auto_describe=True)
WORKER_ALIVE = Gauge("ostium_worker_alive", "1 when the data-plane worker heartbeat is fresh", registry=REGISTRY)
SINGBOX_RUNNING = Gauge("ostium_singbox_running", "1 when sing-box is running", registry=REGISTRY)
ACTIVE_USERS = Gauge("ostium_active_users", "Number of active proxy users", registry=REGISTRY)
ONLINE_USERS = Gauge("ostium_online_users", "Users with traffic in the last 60 seconds", registry=REGISTRY)
UNACK_ALERTS = Gauge("ostium_unacknowledged_alerts", "Unacknowledged alerts", registry=REGISTRY)
DISK_FREE = Gauge("ostium_disk_free_bytes", "Free bytes under the data directory", registry=REGISTRY)


@require_GET
@never_cache
def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "version": __version__})


@require_GET
@never_cache
def readyz(request: HttpRequest) -> JsonResponse:
    state = RuntimeState.load()
    checks = {
        "database": True,
        "worker": state.worker_alive,
        "singbox": state.singbox_running,
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        checks["database"] = False
    ready = checks["database"] and checks["worker"] and checks["singbox"]
    return JsonResponse(
        {
            "status": "ready" if ready else "degraded",
            "checks": checks,
            "applied_revision": state.applied_revision,
            "desired_revision": state.desired_revision,
            "last_error": state.last_error[:500] if state.last_error else "",
        },
        status=200 if ready else 503,
    )


@require_GET
@never_cache
def metrics(request: HttpRequest) -> HttpResponse:
    from ostium.proxy.models import ProxyUser

    state = RuntimeState.load()
    usage = read_usage()
    WORKER_ALIVE.set(1 if state.worker_alive else 0)
    SINGBOX_RUNNING.set(1 if state.singbox_running else 0)
    ACTIVE_USERS.set(ProxyUser.objects.filter(enabled=True).count())
    ONLINE_USERS.set(sum(1 for item in usage.get("users", {}).values() if item.get("online")))
    UNACK_ALERTS.set(Alert.objects.filter(acknowledged_at__isnull=True).count())
    try:
        DISK_FREE.set(shutil.disk_usage(paths.data_dir()).free)
    except OSError:
        DISK_FREE.set(0)
    return HttpResponse(generate_latest(REGISTRY), content_type=CONTENT_TYPE_LATEST)


__all__ = ["healthz", "metrics", "readyz"]
