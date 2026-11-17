"""Ostium package metadata and public constants."""

from __future__ import annotations

from ostium.build_info import build_info

_BUILD = build_info()

__version__ = _BUILD.version

APP_NAME = "Ostium"
API_PREFIX = "/api/v1"
CORE_API_VERSION = "v1"
PROFILE_FORMAT_VERSION = 1
USER_AGENT = f"Ostium/{__version__}"

__all__ = [
    "API_PREFIX",
    "APP_NAME",
    "CORE_API_VERSION",
    "PROFILE_FORMAT_VERSION",
    "USER_AGENT",
    "__version__",
]
