"""Template context shared by the Aurora console."""

from __future__ import annotations

from constance import config as runtime_config
from django.conf import settings

from ostium.operations.models import Alert, RuntimeState
from ostium.version import BUILD_COMMIT, BUILD_DATE, __version__


def console_context(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "app_version": __version__,
        "build_commit": BUILD_COMMIT,
        "build_date": BUILD_DATE,
        "runtime_state": RuntimeState.load(),
        "unack_alerts_count": Alert.objects.filter(acknowledged_at__isnull=True).count(),
        "maintenance_mode": bool(runtime_config.maintenance_mode),
        "public_console": bool(settings.OSTIUM_REQUIRE_TOTP or config_public(request)),
        "server_name": runtime_config.server_name or "Ostium",
    }


def config_public(request) -> bool:
    try:
        return str(runtime_config.public_base_url or "").startswith("https://")
    except Exception:
        return False
