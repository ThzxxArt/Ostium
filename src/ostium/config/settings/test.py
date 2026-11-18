"""Settings used by the test suite.

The database and data directory are redirected to a disposable location by
``tests/conftest.py`` before Django is configured.
"""

from __future__ import annotations

import os

os.environ.setdefault("OSTIUM_DEBUG", "true")
os.environ.setdefault("OSTIUM_TESTING", "true")
os.environ.setdefault("OSTIUM_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "OSTIUM_FIELD_KEY",
    "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
)

from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]
CSRF_TRUSTED_ORIGINS = ["http://localhost", "http://127.0.0.1", "null"]
OSTIUM_REQUIRE_TOTP = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
AXES_ENABLED = env.bool("OSTIUM_TEST_AXES", default=False)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ostium-test",
    }
}

# Keep tests fast while still exercising the real static pipeline on demand.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
