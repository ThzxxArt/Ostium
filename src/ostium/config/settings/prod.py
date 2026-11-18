"""Production settings for a Linux host behind Caddy or an SSH tunnel."""

from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import env

DEBUG = False
SESSION_COOKIE_SECURE = env.bool("OSTIUM_SECURE_COOKIES", default=True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
LANGUAGE_COOKIE_SECURE = SESSION_COOKIE_SECURE

if OSTIUM_BEHIND_PROXY:  # noqa: F405
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

SECURE_SSL_REDIRECT = env.bool("OSTIUM_SSL_REDIRECT", default=OSTIUM_BEHIND_PROXY)  # noqa: F405
# Local health probes speak plain HTTP even when the public site redirects.
SECURE_REDIRECT_EXEMPT = [r"^/healthz$", r"^/readyz$", r"^/metrics$"]
SECURE_HSTS_SECONDS = 31_536_000 if SECURE_SSL_REDIRECT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool(SECURE_SSL_REDIRECT)
SECURE_HSTS_PRELOAD = bool(SECURE_SSL_REDIRECT)

CACHES = {
    "default": {
        # Gunicorn runs multiple workers. Rate limits and CSRF/replay
        # protections must be shared, so a per-process LocMemCache is not
        # sufficient.
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(Path(OSTIUM_DATA_DIR) / "cache"),  # noqa: F405
        "TIMEOUT": 300,
    }
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Refuse to boot a public management plane without TOTP enforcement.
if OSTIUM_PUBLIC_BASE_URL.startswith("https://") and not OSTIUM_REQUIRE_TOTP:  # noqa: F405
    raise ImproperlyConfigured(
        "OSTIUM_PUBLIC_BASE_URL is HTTPS but OSTIUM_REQUIRE_TOTP is false. "
        "Set OSTIUM_REQUIRE_TOTP=true before exposing the console."
    )
