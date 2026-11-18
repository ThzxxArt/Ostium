"""Local development settings."""

from __future__ import annotations

import os

os.environ.setdefault("OSTIUM_DEBUG", "true")

from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]
OSTIUM_REQUIRE_TOTP = env.bool("OSTIUM_REQUIRE_TOTP", default=False)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ostium-dev",
    }
}

INTERNAL_IPS = ["127.0.0.1", "::1"]
