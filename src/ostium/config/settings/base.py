"""Base settings shared by every Ostium deployment."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy
from django.utils.csp import CSP

PACKAGE_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = PACKAGE_DIR.parents[1]

env = environ.Env(
    OSTIUM_DEBUG=(bool, False),
    OSTIUM_ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost", "[::1]"]),
    OSTIUM_CSRF_TRUSTED_ORIGINS=(list, []),
    OSTIUM_TIME_ZONE=(str, "UTC"),
    OSTIUM_LANGUAGE=(str, "zh-hans"),
    OSTIUM_LOG_LEVEL=(str, "INFO"),
    OSTIUM_REQUIRE_TOTP=(bool, False),
    OSTIUM_SECURE_COOKIES=(bool, True),
    OSTIUM_DATA_DIR=(str, str(BASE_DIR / "var")),
    OSTIUM_SINGBOX_PATH=(str, str(BASE_DIR / ".cache" / "bin" / "sing-box")),
    OSTIUM_SINGBOX_BINARY_SHA256=(str, ""),
    OSTIUM_PUBLIC_BASE_URL=(str, ""),
    OSTIUM_EMAIL_URL=(str, "consolemail://"),
    OSTIUM_EMAIL_FROM=(str, "ostium@localhost"),
    OSTIUM_BEHIND_PROXY=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env.bool("OSTIUM_DEBUG")
SECRET_KEY = env.str("OSTIUM_SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-ostium-development-only-key"
    else:
        raise ImproperlyConfigured("OSTIUM_SECRET_KEY must be set in production.")

_field_key = env.str("OSTIUM_FIELD_KEY", default="")
if not _field_key:
    if DEBUG:
        _field_key = base64.b64encode(hashlib.sha256(b"ostium-development-field-key").digest()).decode()
    else:
        raise ImproperlyConfigured("OSTIUM_FIELD_KEY must be set in production.")
try:
    if len(base64.b64decode(_field_key)) != 32:
        raise ValueError
except Exception as exc:
    raise ImproperlyConfigured("OSTIUM_FIELD_KEY must be base64-encoded 32 bytes.") from exc
OSTIUM_FIELD_KEY = _field_key

OSTIUM_DATA_DIR = env.str("OSTIUM_DATA_DIR")
OSTIUM_SINGBOX_PATH = env.str("OSTIUM_SINGBOX_PATH")
OSTIUM_SINGBOX_BINARY_SHA256 = env.str("OSTIUM_SINGBOX_BINARY_SHA256")
OSTIUM_PUBLIC_BASE_URL = env.str("OSTIUM_PUBLIC_BASE_URL").rstrip("/")
OSTIUM_BEHIND_PROXY = env.bool("OSTIUM_BEHIND_PROXY")
OSTIUM_REQUIRE_TOTP = env.bool("OSTIUM_REQUIRE_TOTP")

ALLOWED_HOSTS = env.list("OSTIUM_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("OSTIUM_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "axes",
    "auditlog",
    "constance",
    "constance.backends.database",
    "django_q",
    "rest_framework",
    "rest_framework_api_key",
    "drf_spectacular",
    "django_htmx",
    "health_check",
    "ostium.accounts",
    "ostium.proxy",
    "ostium.certificates",
    "ostium.subscriptions",
    "ostium.engine",
    "ostium.operations",
    "ostium.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "ostium.accounts.middleware.AdminSecurityMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "ostium.config.urls"
WSGI_APPLICATION = "ostium.config.wsgi.application"
ASGI_APPLICATION = "ostium.config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PACKAGE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                "django.template.context_processors.static",
                "django.template.context_processors.csp",
                "ostium.operations.context.console_context",
            ],
            "builtins": ["ostium.templatetags.ostium_ui"],
            "libraries": {"ostium_ui": "ostium.templatetags.ostium_ui"},
        },
    },
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_db_url = env.str("OSTIUM_DB_URL", default=f"sqlite:///{Path(OSTIUM_DATA_DIR) / 'ostium.db'}")
DATABASES = {"default": env.db_url_config(_db_url)}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].update(
        {
            "timeout": 30,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
        }
    )
    DATABASES["default"]["ATOMIC_REQUESTS"] = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication and security
# ---------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "console:dashboard"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
LANGUAGE_COOKIE_HTTPONLY = True
LANGUAGE_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", "blob:"],
    "font-src": [CSP.SELF, "data:"],
    "connect-src": [CSP.SELF],
    "worker-src": [CSP.SELF, "blob:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
SECURE_CSP_REPORT_ONLY = {}

AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/locked_out.html"
AXES_ENABLE_ACCESS_FAILURE_LOG = True

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["ostium.api.permissions.HasOstiumAPIKey"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "30/min", "user": "240/min"},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "ostium.api.errors.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Ostium Server API",
    "DESCRIPTION": "Control-plane API for Ostium Server 0.2.0.",
    "VERSION": "0.2.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

API_KEY_CUSTOM_HEADER = None

# ---------------------------------------------------------------------------
# Django-Q2
# ---------------------------------------------------------------------------

Q_CLUSTER = {
    "name": "ostium",
    "label": "Ostium jobs",
    "workers": env.int("OSTIUM_Q_WORKERS", default=2),
    "timeout": 300,
    "retry": 660,
    "queue_limit": 100,
    "bulk": 10,
    "orm": "default",
    "catch_up": False,
    "save_limit": 500,
    "sync": False,
    "poll": 0.5,
}

# ---------------------------------------------------------------------------
# Constance runtime settings
# ---------------------------------------------------------------------------

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"
CONSTANCE_CONFIG = {
    "server_name": ("Ostium", "Display name used in subscriptions and the console.", str),
    "public_host": ("", "Public hostname advertised in subscriptions, e.g. vpn.example.com.", str),
    "public_base_url": (
        "",
        "Public HTTPS base URL of the console, e.g. https://vpn.example.com. Empty when behind an SSH tunnel.",
        str,
    ),
    "subscription_update_interval": (24, "Hours clients should wait between subscription updates.", int),
    "server_dns_mode": (
        "auto",
        "Server DNS mode: auto probes DoH and falls back to UDP; doh fails closed; udp never probes.",
        str,
    ),
    "server_dns_doh_url": (
        "https://1.1.1.1/dns-query",
        "DNS-over-HTTPS endpoint used by the data plane.",
        str,
    ),
    "block_private_egress": (
        True,
        "Reject RFC1918, CGNAT, loopback, link-local and metadata destinations.",
        bool,
    ),
    "traffic_retention_days": (90, "Days of daily traffic history to keep.", int),
    "audit_retention_days": (365, "Days of audit events to keep.", int),
    "log_level": ("info", "sing-box log level: trace, debug, info, warn, error.", str),
    "auto_backup_enabled": (False, "Create an encrypted backup every night.", bool),
    "auto_backup_keep": (7, "Number of automatic backups to retain.", int),
    "webhook_url": ("", "Optional HTTPS webhook for alerts.", str),
    "webhook_secret": ("", "HMAC-SHA256 secret used to sign webhook payloads.", str),
    "maintenance_mode": (False, "Pause configuration application and show a maintenance banner.", bool),
}
CONSTANCE_CONFIG_FIELDSETS = {
    "General": ("server_name", "public_host", "public_base_url", "subscription_update_interval"),
    "Network": ("server_dns_mode", "server_dns_doh_url", "block_private_egress", "log_level"),
    "Security": ("maintenance_mode",),
    "Notifications": ("webhook_url", "webhook_secret"),
    "Maintenance": (
        "traffic_retention_days",
        "audit_retention_days",
        "auto_backup_enabled",
        "auto_backup_keep",
    ),
}

# ---------------------------------------------------------------------------
# Email, i18n, static files
# ---------------------------------------------------------------------------

vars().update(env.email_url("OSTIUM_EMAIL_URL"))
DEFAULT_FROM_EMAIL = env.str("OSTIUM_EMAIL_FROM")
EMAIL_TIMEOUT = 10

LANGUAGE_CODE = env.str("OSTIUM_LANGUAGE")
LANGUAGES = [("zh-hans", "简体中文"), ("en", "English")]
LOCALE_PATHS = [PACKAGE_DIR / "locale"]
TIME_ZONE = env.str("OSTIUM_TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = Path(OSTIUM_DATA_DIR) / "static"
STATICFILES_DIRS = [PACKAGE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 30
WHITENOISE_ALLOW_ALL_ORIGINS = False

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
DATA_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = env.str("OSTIUM_LOG_LEVEL").upper()
_LOG_DIR = Path(OSTIUM_DATA_DIR) / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)-7s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "ostium_file": {
            "class": "logging.handlers.WatchedFileHandler",
            "filename": str(_LOG_DIR / "ostium.log"),
            "formatter": "plain",
            "delay": True,
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "ostium": {"handlers": ["console", "ostium_file"], "level": LOG_LEVEL, "propagate": False},
        "axes": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

# ---------------------------------------------------------------------------
# Admin / Unfold
# ---------------------------------------------------------------------------

UNFOLD = {
    "SITE_TITLE": "Ostium Server",
    "SITE_HEADER": "Ostium",
    "SITE_SUBHEADER": "Private proxy server",
    "SITE_URL": "/",
    "SITE_SYMBOL": "shield",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "SHOW_LANGUAGES": False,
    "SHOW_BACK_BUTTON": False,
    "STYLES": ["/static/css/app.css"],
    "SCRIPTS": ["/static/js/console.js"],
    "COLORS": {
        "primary": {
            "50": "#effefb",
            "100": "#c8fff4",
            "200": "#91ffea",
            "300": "#52f7dd",
            "400": "#1fe4cb",
            "500": "#06c8b2",
            "600": "#00a190",
            "700": "#058176",
            "800": "#0a665f",
            "900": "#0d544f",
            "950": "#003331",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Console",
                "separator": False,
                "items": [
                    {
                        "title": "Overview",
                        "icon": "dashboard",
                        "link": reverse_lazy("console:dashboard"),
                    },
                    {
                        "title": "Users",
                        "icon": "group",
                        "link": reverse_lazy("console:users"),
                    },
                    {
                        "title": "Subscriptions",
                        "icon": "link",
                        "link": reverse_lazy("console:subscriptions"),
                    },
                    {
                        "title": "Inbounds",
                        "icon": "lan",
                        "link": reverse_lazy("console:inbounds"),
                    },
                    {
                        "title": "Connections",
                        "icon": "swap_horiz",
                        "link": reverse_lazy("console:connections"),
                    },
                ],
            },
            {
                "title": "Operations",
                "separator": True,
                "items": [
                    {
                        "title": "Certificates",
                        "icon": "verified_user",
                        "link": reverse_lazy("console:certificates"),
                    },
                    {
                        "title": "Logs",
                        "icon": "article",
                        "link": reverse_lazy("console:logs"),
                    },
                    {
                        "title": "Jobs",
                        "icon": "schedule",
                        "link": reverse_lazy("console:jobs"),
                    },
                    {
                        "title": "System",
                        "icon": "monitor_heart",
                        "link": reverse_lazy("console:system"),
                    },
                    {
                        "title": "Audit",
                        "icon": "history",
                        "link": reverse_lazy("console:audit"),
                    },
                    {
                        "title": "Settings",
                        "icon": "settings",
                        "link": reverse_lazy("console:settings"),
                    },
                ],
            },
            {
                "title": "Django admin",
                "separator": True,
                "items": [
                    {
                        "title": "Proxy users",
                        "icon": "manage_accounts",
                        "link": reverse_lazy("admin:proxy_proxyuser_changelist"),
                    },
                    {
                        "title": "Inbound records",
                        "icon": "dns",
                        "link": reverse_lazy("admin:proxy_inbound_changelist"),
                    },
                    {
                        "title": "Certificates",
                        "icon": "lock",
                        "link": reverse_lazy("admin:certificates_certificate_changelist"),
                    },
                    {
                        "title": "Admins",
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                ],
            },
        ],
    },
}

# ---------------------------------------------------------------------------
# Ostium paths and policy
# ---------------------------------------------------------------------------

OSTIUM_WORKER_HEARTBEAT_TIMEOUT = 15
OSTIUM_CONFIG_CHECK_TIMEOUT = 30
OSTIUM_SINGBOX_CLASH_ADDRESS = "127.0.0.1:19090"
OSTIUM_SINGBOX_STATS_ADDRESS = "127.0.0.1:19091"
OSTIUM_QUOTA_WARN_THRESHOLDS = (0.8, 0.9)
OSTIUM_SUPPORTED_LOCALES = ("zh-hans", "en")

if env.bool("OSTIUM_TESTING", default=False):
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

os.makedirs(OSTIUM_DATA_DIR, exist_ok=True)

OTP_TOTP_ISSUER = "Ostium"
OTP_TOTP_THROTTLE_FACTOR = 1
